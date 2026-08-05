#!/usr/bin/env python3
"""Führt LLBBDivA und LLBBDivB zur Landesliga Baseball 2026 zusammen.

Die Datei kann in VS Code geöffnet und über „Run Python File“ gestartet werden.
Kommandozeilenargumente und externe Python-Pakete sind nicht erforderlich.

Voraussetzung: ``league_data_fetcher.py`` liegt im gleichen Ordner.
Mannschaften werden über league_entry.id, Spiele über match.id und Spieler über
league_entry.id + person.id dedupliziert. Die Tabelle wird aus den eindeutigen
abgeschlossenen Spielen neu berechnet.
"""

from __future__ import annotations

import copy
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from league_data_fetcher import (
    BASE_URL,
    fetch_discovery_payloads,
    fetch_team_dataset,
    write_json,
)

SEASON = 2026
LANDESLIGA_GROUPS = [
    {"id": 6208, "acronym": "LLBBDivA", "name": "Landesliga Baseball"},
    {"id": 6209, "acronym": "LLBBDivB", "name": "Landesliga Baseball"},
]
OUTPUT_ROOT = Path("bsm_league_data")
OUTPUT_DIR_NAME = "landesliga_2026"
TIMEOUT = 30.0
RETRIES = 3
REQUEST_DELAY = 0.2


def as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def nonempty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def unique_sorted(values: Iterable[Any]) -> list[Any]:
    return sorted({value for value in values if value is not None})


def merge_group_teams(*groups: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """여러 그룹의 팀을 league_entry ID 기준으로 합친다."""
    merged: dict[int, dict[str, Any]] = {}

    for group in groups:
        for team in group:
            entry_id = as_int(team.get("id"))
            if entry_id is None:
                continue

            current = merged.setdefault(
                entry_id,
                {
                    "id": entry_id,
                    "name": nonempty(team.get("name")) or f"League Entry {entry_id}",
                    "acronym": nonempty(team.get("acronym")),
                    "club": copy.deepcopy(team.get("club")),
                    "clubs": copy.deepcopy(team.get("clubs")) or [],
                    "sources": [],
                    "group_ids": [],
                    "group_acronyms": [],
                    "primary_group_ids": [],
                    "secondary_group_ids": [],
                },
            )

            candidate_name = nonempty(team.get("name"))
            if candidate_name and (
                current["name"].startswith("League Entry ")
                or len(candidate_name) > len(current["name"])
            ):
                current["name"] = candidate_name

            if not current.get("acronym") and nonempty(team.get("acronym")):
                current["acronym"] = nonempty(team.get("acronym"))
            if not current.get("club") and team.get("club"):
                current["club"] = copy.deepcopy(team.get("club"))
            if not current.get("clubs") and team.get("clubs"):
                current["clubs"] = copy.deepcopy(team.get("clubs"))

            for list_key in (
                "sources",
                "group_ids",
                "group_acronyms",
                "primary_group_ids",
                "secondary_group_ids",
            ):
                for value in team.get(list_key, []) or []:
                    if value not in current[list_key]:
                        current[list_key].append(value)

    for team in merged.values():
        team["group_ids"] = unique_sorted(team["group_ids"])
        team["group_acronyms"] = unique_sorted(team["group_acronyms"])
        team["primary_group_ids"] = unique_sorted(team["primary_group_ids"])
        team["secondary_group_ids"] = unique_sorted(team["secondary_group_ids"])

    return sorted(
        merged.values(),
        key=lambda row: (str(row.get("name", "")).casefold(), row["id"]),
    )


def enrich_discovered_teams(
    teams: Iterable[dict[str, Any]], group: dict[str, Any]
) -> list[dict[str, Any]]:
    """기존 fetcher가 찾은 팀에 어느 그룹에서 발견됐는지 표시한다."""
    enriched: list[dict[str, Any]] = []
    for team in teams:
        row = copy.deepcopy(team)
        row["sources"] = [
            f"{group['acronym']}:{source}" for source in row.get("sources", [])
        ]
        row["group_ids"] = [group["id"]]
        row["group_acronyms"] = [group["acronym"]]
        row.setdefault("primary_group_ids", [])
        row.setdefault("secondary_group_ids", [])
        enriched.append(row)
    return enriched


def match_entry_to_team(
    entry: Any,
    source: str,
    primary_group_id: int | None,
    secondary_group_id: int | None,
) -> dict[str, Any] | None:
    """경기 응답의 nested league_entry/team 구조를 팀 메타데이터로 바꾼다."""
    if not isinstance(entry, dict):
        return None
    entry_id = as_int(entry.get("id"))
    if entry_id is None:
        return None

    team = entry.get("team") if isinstance(entry.get("team"), dict) else {}
    clubs = team.get("clubs") if isinstance(team.get("clubs"), list) else []
    first_club = next((c for c in clubs if isinstance(c, dict)), {})

    name = (
        nonempty(team.get("name"))
        or nonempty(entry.get("name"))
        or nonempty(first_club.get("short_name"))
        or nonempty(first_club.get("name"))
        or f"League Entry {entry_id}"
    )
    acronym = (
        nonempty(team.get("short_name"))
        or nonempty(entry.get("acronym"))
        or nonempty(first_club.get("acronym"))
    )

    return {
        "id": entry_id,
        "name": name,
        "acronym": acronym,
        "club": copy.deepcopy(first_club) if first_club else None,
        "clubs": copy.deepcopy(clubs),
        "sources": [source],
        "group_ids": unique_sorted([primary_group_id, secondary_group_id]),
        "group_acronyms": [],
        "primary_group_ids": unique_sorted([primary_group_id]),
        "secondary_group_ids": unique_sorted([secondary_group_id]),
    }


def extract_match_teams(
    matches: Iterable[dict[str, Any]], source_group: dict[str, Any]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        primary = match.get("league") if isinstance(match.get("league"), dict) else {}
        secondary = (
            match.get("second_league")
            if isinstance(match.get("second_league"), dict)
            else {}
        )
        primary_id = as_int(primary.get("id"))
        secondary_id = as_int(secondary.get("id"))
        group_acronyms = unique_sorted(
            [nonempty(primary.get("acronym")), nonempty(secondary.get("acronym"))]
        )

        for side in ("home_league_entry", "away_league_entry"):
            normalized = match_entry_to_team(
                match.get(side),
                source=f"{source_group['acronym']}:group_matches",
                primary_group_id=primary_id,
                secondary_group_id=secondary_id,
            )
            if normalized is not None:
                normalized["group_acronyms"] = group_acronyms
                result.append(normalized)

    return merge_group_teams(result)


def dedupe_matches(*groups: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """경기를 match.id 기준으로 합치며 출처 그룹 정보도 보존한다."""
    merged: dict[str, dict[str, Any]] = {}

    for group in groups:
        for match in group:
            if not isinstance(match, dict):
                continue
            match_id = as_int(match.get("id"))
            if match_id is not None:
                key = f"id:{match_id}"
            else:
                key = "json:" + json.dumps(match, ensure_ascii=False, sort_keys=True)

            candidate = copy.deepcopy(match)
            candidate.setdefault("source_group_ids", [])
            if key not in merged:
                merged[key] = candidate
                continue

            current = merged[key]
            for group_id in candidate.get("source_group_ids", []) or []:
                if group_id not in current.setdefault("source_group_ids", []):
                    current["source_group_ids"].append(group_id)

            # 동일 경기의 한 응답에만 존재하는 최상위 필드가 있으면 보완한다.
            for field, value in candidate.items():
                if field not in current or current[field] in (None, "", [], {}):
                    current[field] = copy.deepcopy(value)

    rows = list(merged.values())
    for row in rows:
        row["source_group_ids"] = unique_sorted(row.get("source_group_ids", []))
    return sorted(rows, key=lambda row: (as_int(row.get("id")) is None, as_int(row.get("id")) or 0))


def player_identity(row: dict[str, Any]) -> str:
    entry = row.get("league_entry") if isinstance(row.get("league_entry"), dict) else {}
    person = row.get("person") if isinstance(row.get("person"), dict) else {}
    entry_id = as_int(entry.get("id"))
    person_id = as_int(person.get("id"))
    if entry_id is not None and person_id is not None:
        return f"entry:{entry_id}:person:{person_id}"
    return "json:" + json.dumps(row, ensure_ascii=False, sort_keys=True)


def dedupe_player_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = player_identity(row)
        if key not in merged:
            merged[key] = copy.deepcopy(row)
    return list(merged.values())


def compute_combined_standings(
    matches: Iterable[dict[str, Any]], teams: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """중복 제거된 완료 경기로 비공식 통합 순위를 계산한다."""
    table: dict[int, dict[str, Any]] = {}

    for team in teams:
        entry_id = as_int(team.get("id"))
        if entry_id is None:
            continue
        table[entry_id] = {
            "league_entry_id": entry_id,
            "team": team.get("name") or f"League Entry {entry_id}",
            "acronym": team.get("acronym"),
            "games": 0,
            "wins": 0,
            "losses": 0,
            "ties": 0,
            "runs_for": 0,
            "runs_against": 0,
            "run_diff": 0,
            "win_pct": 0.0,
        }

    for match in matches:
        if not isinstance(match, dict) or match.get("state") not in {"played", "manually_valued"}:
            continue

        home_entry = (
            match.get("home_league_entry")
            if isinstance(match.get("home_league_entry"), dict)
            else {}
        )
        away_entry = (
            match.get("away_league_entry")
            if isinstance(match.get("away_league_entry"), dict)
            else {}
        )
        home_id = as_int(home_entry.get("id"))
        away_id = as_int(away_entry.get("id"))
        home_runs = as_int(match.get("home_runs"))
        away_runs = as_int(match.get("away_runs"))

        if None in (home_id, away_id, home_runs, away_runs):
            continue

        for entry_id, entry in ((home_id, home_entry), (away_id, away_entry)):
            if entry_id not in table:
                nested_team = entry.get("team") if isinstance(entry.get("team"), dict) else {}
                table[entry_id] = {
                    "league_entry_id": entry_id,
                    "team": nested_team.get("name") or f"League Entry {entry_id}",
                    "acronym": nested_team.get("short_name"),
                    "games": 0,
                    "wins": 0,
                    "losses": 0,
                    "ties": 0,
                    "runs_for": 0,
                    "runs_against": 0,
                    "run_diff": 0,
                    "win_pct": 0.0,
                }

        home = table[home_id]
        away = table[away_id]
        home["games"] += 1
        away["games"] += 1
        home["runs_for"] += home_runs
        home["runs_against"] += away_runs
        away["runs_for"] += away_runs
        away["runs_against"] += home_runs

        if home_runs > away_runs:
            home["wins"] += 1
            away["losses"] += 1
        elif away_runs > home_runs:
            away["wins"] += 1
            home["losses"] += 1
        else:
            home["ties"] += 1
            away["ties"] += 1

    rows = list(table.values())
    for row in rows:
        decisions = row["wins"] + row["losses"]
        row["win_pct"] = round(row["wins"] / decisions, 3) if decisions else 0.0
        row["run_diff"] = row["runs_for"] - row["runs_against"]

    rows.sort(
        key=lambda row: (
            -row["win_pct"],
            -row["wins"],
            -row["run_diff"],
            -row["runs_for"],
            str(row["team"]).casefold(),
        )
    )
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


def annotate_match_sources(matches: Any, group_id: int) -> list[dict[str, Any]]:
    if not isinstance(matches, list):
        return []
    result: list[dict[str, Any]] = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        row = copy.deepcopy(match)
        row["source_group_ids"] = unique_sorted(
            [*(row.get("source_group_ids", []) or []), group_id]
        )
        result.append(row)
    return result


def render_report(report: dict[str, Any]) -> str:
    lines = [
        "BSM LANDESLIGA MERGE REPORT",
        "=" * 78,
        f"Erstellt        : {report['generated_at']}",
        f"Saison          : {report['league']['season']}",
        f"Zusammengeführt : {report['league']['name']}",
        f"Quellgruppen    : {', '.join(g['acronym'] + '=' + str(g['id']) for g in report['league']['source_groups'])}",
        f"Mannschaften    : {report['counts']['teams']}",
        f"Eindeutige Spiele: {report['counts']['matches']}",
        f"Gespielte Spiele: {report['counts']['played_matches']}",
        f"Batter          : {report['counts']['batters']}",
        f"Pitcher         : {report['counts']['pitchers']}",
        "",
        "[GRUPPENERKENNUNG]",
    ]

    for group in report["groups"]:
        lines.append(
            f"- {group['acronym']} ({group['id']}): "
            f"teams={group['teams']} endpoint_matches={group['matches']}"
        )
        for failure in group.get("failures", []):
            lines.append(f"    [FAIL] {failure.get('label')}: {failure.get('error')}")

    lines.extend(["", "[MANNSCHAFTEN]"])
    for team in report["teams"]:
        lines.append(
            f"- entry={team['id']} | {team.get('acronym') or '-'} | {team.get('name')} "
            f"| primary={team.get('primary_group_ids', [])} "
            f"| secondary={team.get('secondary_group_ids', [])}"
        )

    lines.extend(["", "[TEAM-STATISTIKEN]"])
    for item in report["team_fetches"]:
        marker = "OK" if item.get("ok") else "FAIL"
        line = (
            f"[{marker}] {item.get('dataset', '-'):<8} "
            f"entry={item.get('league_entry_id')} team={item.get('team')} "
            f"rows={item.get('rows', 0)}"
        )
        if item.get("error"):
            line += f" error={item['error']}"
        lines.append(line)

    lines.extend(
        [
            "",
            "[AUSGABE]",
            *[f"- {path}" for path in report["output_files"].values()],
            "",
            "combined.json kann direkt von der Website eingelesen werden.",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> int:
    output_dir = (OUTPUT_ROOT / OUTPUT_DIR_NAME).resolve()
    raw_dir = output_dir / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    print("[Landesliga-Zusammenführung]")
    print("  - LLBBDivA: 6208")
    print("  - LLBBDivB: 6209")
    print("  - Deduplizierung über Match-ID und League-Entry-ID.\n")

    group_reports: list[dict[str, Any]] = []
    all_team_groups: list[list[dict[str, Any]]] = []
    all_match_groups: list[list[dict[str, Any]]] = []

    for index, group in enumerate(LANDESLIGA_GROUPS, start=1):
        print(f"[{index}/{len(LANDESLIGA_GROUPS)}] {group['acronym']} ({group['id']}) wird geladen")
        group_raw_dir = raw_dir / f"{group['acronym']}_{group['id']}"
        discovery, discovered_teams, failures = fetch_discovery_payloads(
            base_url=BASE_URL,
            league_id=group["id"],
            raw_dir=group_raw_dir,
            timeout=TIMEOUT,
            retries=RETRIES,
            delay=REQUEST_DELAY,
        )

        matches = annotate_match_sources(discovery.get("group_matches"), group["id"])
        teams_from_discovery = enrich_discovered_teams(discovered_teams, group)
        teams_from_matches = extract_match_teams(matches, group)
        group_teams = merge_group_teams(teams_from_discovery, teams_from_matches)

        all_team_groups.append(group_teams)
        all_match_groups.append(matches)
        group_reports.append(
            {
                "id": group["id"],
                "acronym": group["acronym"],
                "teams": len(group_teams),
                "matches": len(matches),
                "failures": failures,
            }
        )
        print(f"      teams={len(group_teams)}, matches={len(matches)}")

    teams = merge_group_teams(*all_team_groups)
    matches = dedupe_matches(*all_match_groups)
    standings = compute_combined_standings(matches, teams)

    print(f"\nMannschaften gesamt: {len(teams)}")
    print(f"Spiele gesamt: {len(matches)}")

    batting_rows: list[dict[str, Any]] = []
    pitching_rows: list[dict[str, Any]] = []
    team_fetches: list[dict[str, Any]] = []
    total_requests = len(teams) * 2
    current_request = 0

    for team in teams:
        for dataset in ("batting", "pitching"):
            current_request += 1
            print(
                f"[{current_request}/{total_requests}] "
                f"{team.get('name')} ({team['id']}) {dataset}"
            )
            rows, fetch_report = fetch_team_dataset(
                base_url=BASE_URL,
                league_entry=team,
                dataset=dataset,
                raw_dir=raw_dir / "teams",
                timeout=TIMEOUT,
                retries=RETRIES,
            )
            team_fetches.append(fetch_report)
            if dataset == "batting":
                batting_rows.extend(rows)
            else:
                pitching_rows.extend(rows)
            if REQUEST_DELAY > 0 and current_request < total_requests:
                time.sleep(REQUEST_DELAY)

    batting_rows = dedupe_player_rows(batting_rows)
    pitching_rows = dedupe_player_rows(pitching_rows)
    played_matches = sum(
        1
        for match in matches
        if match.get("state") == "played"
        and as_int(match.get("home_runs")) is not None
        and as_int(match.get("away_runs")) is not None
    )

    generated_at = datetime.now(timezone.utc).isoformat()
    league_meta = {
        "id": "landesliga-2026",
        "name": "Landesliga Baseball",
        "acronym": "LLBB",
        "season": SEASON,
        "merged": True,
        "source_groups": copy.deepcopy(LANDESLIGA_GROUPS),
        "merge_rules": {
            "teams": "league_entry.id",
            "matches": "match.id",
            "players": "league_entry.id + person.id",
            "standings": "unique played matches",
        },
    }

    payloads = {
        "teams": {"generated_at": generated_at, "league": league_meta, "teams": teams},
        "matches": {"generated_at": generated_at, "league": league_meta, "matches": matches},
        "standings": {
            "generated_at": generated_at,
            "league": league_meta,
            "note": "Inoffizielle Gesamttabelle aus deduplizierten abgeschlossenen Spielen von DivA und DivB.",
            "standings": standings,
        },
        "batting": {
            "generated_at": generated_at,
            "league": league_meta,
            "players": batting_rows,
        },
        "pitching": {
            "generated_at": generated_at,
            "league": league_meta,
            "players": pitching_rows,
        },
    }
    combined = {
        "generated_at": generated_at,
        "league": league_meta,
        "counts": {
            "teams": len(teams),
            "matches": len(matches),
            "played_matches": played_matches,
            "batters": len(batting_rows),
            "pitchers": len(pitching_rows),
        },
        "teams": teams,
        "matches": matches,
        "standings": standings,
        "batting": batting_rows,
        "pitching": pitching_rows,
    }

    output_files = {
        "teams": output_dir / "teams.json",
        "matches": output_dir / "matches.json",
        "standings": output_dir / "standings.json",
        "batting": output_dir / "batting.json",
        "pitching": output_dir / "pitching.json",
        "combined": output_dir / "combined.json",
        "fetch_report_json": output_dir / "fetch_report.json",
        "fetch_report_text": output_dir / "fetch_report.txt",
    }

    for name in ("teams", "matches", "standings", "batting", "pitching"):
        write_json(output_files[name], payloads[name])
    write_json(output_files["combined"], combined)

    report = {
        "generated_at": generated_at,
        "league": league_meta,
        "counts": combined["counts"],
        "groups": group_reports,
        "teams": teams,
        "team_fetches": team_fetches,
        "output_files": {key: str(path) for key, path in output_files.items()},
    }
    write_json(output_files["fetch_report_json"], report)
    output_files["fetch_report_text"].write_text(render_report(report), encoding="utf-8")

    print("\nSpeichern abgeschlossen")
    print(f"  {output_files['combined']}")
    print(f"  {output_files['fetch_report_text']}")
    return 0


def main() -> int:
    try:
        return run()
    except KeyboardInterrupt:
        print("\nAusführung abgebrochen.")
        return 130
    except Exception as exc:
        print(f"\nFehler: {type(exc).__name__}: {exc}")
        print("Bitte die Fehlermeldung und – falls vorhanden – fetch_report.txt prüfen.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
