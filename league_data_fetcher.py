#!/usr/bin/env python3
"""Hilfsmodul zum Abruf vollständiger BSM-Ligastatistiken.

Das Modul erkennt League-Entry-IDs aus Liga-Statistiken und Spielplänen und
lädt anschließend die Batting- und Pitching-Daten jeder Mannschaft. Es werden
nur Module der Python-Standardbibliothek verwendet.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "https://bsm.baseball-softball.de"
LEAGUE_ENTRY_KEYS = {
    "league_entry",
    "home_league_entry",
    "away_league_entry",
}


def as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def safe_slug(value: Any) -> str:
    text = str(value).strip()
    text = re.sub(r'[\\/:*?"<>|]+', "_", text)
    text = re.sub(r"\s+", "_", text)
    return text.strip("._") or "unknown"


def entity_name(entity: dict[str, Any]) -> str | None:
    for key in ("name", "display_name", "short_name", "team_name", "club_name"):
        value = entity.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def normalize_league_entry(entity: dict[str, Any], source: str) -> dict[str, Any] | None:
    entry_id = as_int(entity.get("id"))
    if entry_id is None:
        return None

    club = entity.get("club") if isinstance(entity.get("club"), dict) else {}
    name = entity_name(entity) or entity_name(club) or f"League Entry {entry_id}"
    acronym = (
        entity.get("acronym")
        or entity.get("short_name")
        or club.get("acronym")
        or club.get("short_name")
    )

    return {
        "id": entry_id,
        "name": name,
        "acronym": acronym,
        "club": copy.deepcopy(club) if club else None,
        "sources": [source],
    }


def extract_league_entries(payload: Any, source: str) -> list[dict[str, Any]]:
    """응답 전체에서 league_entry 계열 객체를 찾아 ID 기준으로 중복 제거한다."""
    found: dict[int, dict[str, Any]] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in LEAGUE_ENTRY_KEYS and isinstance(value, dict):
                    normalized = normalize_league_entry(value, source)
                    if normalized is not None:
                        existing = found.get(normalized["id"])
                        if existing is None:
                            found[normalized["id"]] = normalized
                        else:
                            merged = merge_league_entries([existing], [normalized])[0]
                            found[normalized["id"]] = merged
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return sorted(found.values(), key=lambda item: item["id"])


def merge_league_entries(*groups: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """여러 출처의 league_entry 목록을 ID 기준으로 합친다."""
    merged: dict[int, dict[str, Any]] = {}

    for group in groups:
        for item in group:
            entry_id = as_int(item.get("id"))
            if entry_id is None:
                continue

            current = merged.setdefault(
                entry_id,
                {
                    "id": entry_id,
                    "name": item.get("name") or f"League Entry {entry_id}",
                    "acronym": item.get("acronym"),
                    "club": copy.deepcopy(item.get("club")),
                    "sources": [],
                },
            )

            if not current.get("acronym") and item.get("acronym"):
                current["acronym"] = item["acronym"]
            if (
                current.get("name", "").startswith("League Entry ")
                and item.get("name")
            ):
                current["name"] = item["name"]
            if not current.get("club") and item.get("club"):
                current["club"] = copy.deepcopy(item["club"])

            for source in item.get("sources", []):
                if source not in current["sources"]:
                    current["sources"].append(source)

    return sorted(merged.values(), key=lambda item: (str(item.get("name", "")).casefold(), item["id"]))


def attach_league_entry(
    rows: Iterable[dict[str, Any]], league_entry: dict[str, Any]
) -> list[dict[str, Any]]:
    """선수 행에 팀 정보가 없을 때만 기본 league_entry를 복사해 넣는다."""
    result: list[dict[str, Any]] = []
    fallback = {
        key: copy.deepcopy(value)
        for key, value in league_entry.items()
        if key not in {"sources"}
    }

    for row in rows:
        if not isinstance(row, dict):
            continue
        cloned = copy.deepcopy(row)
        if not isinstance(cloned.get("league_entry"), dict):
            cloned["league_entry"] = copy.deepcopy(fallback)
        result.append(cloned)

    return result


def fetch_json(url: str, timeout: float, retries: int) -> dict[str, Any]:
    last_error = "unknown error"

    for attempt in range(1, retries + 1):
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Berlin-Sluggers-League-Fetcher/1.0",
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                payload = json.loads(raw.decode(charset, errors="replace"))
                return {
                    "ok": True,
                    "status": getattr(response, "status", 200),
                    "url": url,
                    "payload": payload,
                    "error": None,
                    "attempts": attempt,
                }
        except HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                body = ""
            last_error = f"HTTP {exc.code}: {exc.reason}; body={body!r}"
            if 400 <= exc.code < 500:
                break
        except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"

        if attempt < retries:
            time.sleep(min(attempt * 1.5, 4.0))

    return {
        "ok": False,
        "status": None,
        "url": url,
        "payload": None,
        "error": last_error,
        "attempts": retries,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def data_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def discover_resources(base_url: str, league_id: int) -> list[tuple[str, str]]:
    base = base_url.rstrip("/")
    return [
        ("league_batting", f"{base}/leagues/{league_id}/statistics/batting.json"),
        ("league_pitching", f"{base}/leagues/{league_id}/statistics/pitching.json"),
        ("group_table", f"{base}/league_groups/{league_id}/table.json"),
        ("group_matches", f"{base}/league_groups/{league_id}/matches.json?compact=true"),
    ]


def fetch_discovery_payloads(
    base_url: str,
    league_id: int,
    raw_dir: Path,
    timeout: float,
    retries: int,
    delay: float,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    results: dict[str, Any] = {}
    entry_groups: list[list[dict[str, Any]]] = []
    failures: list[dict[str, Any]] = []

    resources = discover_resources(base_url, league_id)
    for index, (label, url) in enumerate(resources):
        response = fetch_json(url, timeout=timeout, retries=retries)
        result = {
            "label": label,
            "url": url,
            "ok": response["ok"],
            "status": response["status"],
            "error": response["error"],
        }

        if response["ok"]:
            payload = response["payload"]
            results[label] = payload
            write_json(raw_dir / f"{label}.json", payload)
            entries = extract_league_entries(payload, source=label)
            entry_groups.append(entries)
            result["league_entries"] = len(entries)
        else:
            failures.append(result)

        if delay > 0 and index < len(resources) - 1:
            time.sleep(delay)

    return results, merge_league_entries(*entry_groups), failures


def fetch_team_dataset(
    base_url: str,
    league_entry: dict[str, Any],
    dataset: str,
    raw_dir: Path,
    timeout: float,
    retries: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    entry_id = league_entry["id"]
    url = f"{base_url.rstrip('/')}/league_entries/{entry_id}/statistics/{dataset}.json"
    response = fetch_json(url, timeout=timeout, retries=retries)
    report = {
        "league_entry_id": entry_id,
        "team": league_entry.get("name"),
        "dataset": dataset,
        "url": url,
        "ok": response["ok"],
        "status": response["status"],
        "error": response["error"],
        "rows": 0,
    }

    if not response["ok"]:
        return [], report

    payload = response["payload"]
    team_slug = safe_slug(f"{league_entry.get('acronym') or league_entry.get('name')}_{entry_id}")
    write_json(raw_dir / team_slug / f"{dataset}.json", payload)
    rows = attach_league_entry(data_rows(payload), league_entry)
    report["rows"] = len(rows)
    report["top_level_keys"] = sorted(payload.keys()) if isinstance(payload, dict) else []
    return rows, report


def render_report(report: dict[str, Any]) -> str:
    lines = [
        "BSM LIGA-DATENABRUF",
        "=" * 76,
        f"Erstellt  : {report['generated_at']}",
        f"Liga-ID   : {report['league_id']}",
        f"Teams     : {len(report['teams'])}",
        f"Batter    : {len(report['batting']['players'])}",
        f"Pitcher   : {len(report['pitching']['players'])}",
        "",
        "[GEFUNDENE LEAGUE ENTRIES]",
    ]

    for team in report["teams"]:
        lines.append(
            f"- id={team['id']} | acronym={team.get('acronym') or '-'} | "
            f"name={team.get('name') or '-'} | sources={team.get('sources', [])}"
        )

    lines.extend(["", "[TEAM-ABRUFERGEBNISSE]"])
    for item in report["team_fetches"]:
        marker = "OK" if item["ok"] else "FAIL"
        message = (
            f"[{marker}] {item['dataset']:<8} entry={item['league_entry_id']} "
            f"team={item.get('team')} rows={item.get('rows', 0)}"
        )
        if item.get("error"):
            message += f" error={item['error']}"
        lines.append(message)

    if report["discovery_failures"]:
        lines.extend(["", "[FEHLER BEI DER ERKENNUNG]"])
        for item in report["discovery_failures"]:
            lines.append(f"- {item['label']}: {item['error']}")

    lines.extend(
        [
            "",
            "[AUSGABEDATEIEN]",
            f"- {report['output_files']['teams']}",
            f"- {report['output_files']['batting']}",
            f"- {report['output_files']['pitching']}",
            f"- {report['output_files']['combined']}",
            "",
            "fetch_report.txt und combined.json enthalten das Ergebnis.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> int:
    output_root = Path(args.output).resolve()
    league_dir = output_root / f"league_{args.league_id}"
    raw_dir = league_dir / "raw"
    league_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    print(f"Mannschaften der Liga {args.league_id} werden gesucht …")
    discovery, teams, discovery_failures = fetch_discovery_payloads(
        base_url=args.base_url,
        league_id=args.league_id,
        raw_dir=raw_dir,
        timeout=args.timeout,
        retries=args.retries,
        delay=args.delay,
    )

    if not teams:
        print("Keine League Entries gefunden.")
        print("Bitte die API-Antworten im raw-Ordner prüfen.")
        return 1

    print(f"Gefundene League Entries: {len(teams)}")
    for team in teams:
        print(f"  {team['id']} | {team.get('acronym') or '-'} | {team.get('name')}")

    batting_players: list[dict[str, Any]] = []
    pitching_players: list[dict[str, Any]] = []
    team_fetches: list[dict[str, Any]] = []

    total_requests = len(teams) * 2
    request_number = 0
    for team in teams:
        for dataset in ("batting", "pitching"):
            request_number += 1
            print(
                f"[{request_number}/{total_requests}] {team.get('name')} "
                f"({team['id']}) {dataset}"
            )
            rows, fetch_report = fetch_team_dataset(
                base_url=args.base_url,
                league_entry=team,
                dataset=dataset,
                raw_dir=raw_dir,
                timeout=args.timeout,
                retries=args.retries,
            )
            team_fetches.append(fetch_report)
            if dataset == "batting":
                batting_players.extend(rows)
            else:
                pitching_players.extend(rows)
            if args.delay > 0 and request_number < total_requests:
                time.sleep(args.delay)

    generated_at = datetime.now(timezone.utc).isoformat()
    teams_payload = {
        "generated_at": generated_at,
        "league_id": args.league_id,
        "teams": teams,
    }
    batting_payload = {
        "generated_at": generated_at,
        "league_id": args.league_id,
        "players": batting_players,
    }
    pitching_payload = {
        "generated_at": generated_at,
        "league_id": args.league_id,
        "players": pitching_players,
    }
    combined_payload = {
        "generated_at": generated_at,
        "league_id": args.league_id,
        "teams": teams,
        "batting": batting_players,
        "pitching": pitching_players,
    }

    teams_path = league_dir / "teams.json"
    batting_path = league_dir / "batting.json"
    pitching_path = league_dir / "pitching.json"
    combined_path = league_dir / "combined.json"
    write_json(teams_path, teams_payload)
    write_json(batting_path, batting_payload)
    write_json(pitching_path, pitching_payload)
    write_json(combined_path, combined_payload)

    report = {
        "generated_at": generated_at,
        "league_id": args.league_id,
        "teams": teams,
        "batting": batting_payload,
        "pitching": pitching_payload,
        "team_fetches": team_fetches,
        "discovery_failures": discovery_failures,
        "discovery_resource_keys": sorted(discovery.keys()),
        "output_files": {
            "teams": str(teams_path),
            "batting": str(batting_path),
            "pitching": str(pitching_path),
            "combined": str(combined_path),
        },
    }
    write_json(league_dir / "fetch_report.json", report)
    report_text = render_report(report)
    (league_dir / "fetch_report.txt").write_text(report_text, encoding="utf-8")

    print("\n" + report_text)
    return 0 if any(item["ok"] for item in team_fetches) else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Erstellt einen vollständigen Liga-Datensatz aus BSM League Entries."
    )
    parser.add_argument("--league-id", type=int, required=True, help="z. B. 6205 oder 6209")
    parser.add_argument("--output", default="bsm_league_data", help="Ausgabeordner")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.2, help="Pause zwischen Anfragen in Sekunden")
    return parser


def main() -> int:
    return run(build_parser().parse_args())


if __name__ == "__main__":
    sys.exit(main())
