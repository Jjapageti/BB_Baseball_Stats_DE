#!/usr/bin/env python3
"""Erstellt den vollständigen Datensatz der Verbandsliga Baseball 2026.

Die Datei kann in VS Code geöffnet und über „Run Python File“ gestartet werden.
Es sind keine Kommandozeilenargumente und keine externen Python-Pakete nötig.
"""

from __future__ import annotations

import copy
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from league_data_fetcher import BASE_URL, fetch_discovery_payloads, fetch_team_dataset, write_json
from landesliga_data_fetcher_vscode import (
    annotate_match_sources,
    compute_combined_standings,
    dedupe_matches,
    dedupe_player_rows,
    enrich_discovered_teams,
    extract_match_teams,
    merge_group_teams,
)

LEAGUE_ID = 6205
LEAGUE_NAME = "Verbandsliga Baseball"
LEAGUE_ACRONYM = "VLBB"
SEASON = 2026
OUTPUT_ROOT = Path("bsm_league_data")
OUTPUT_DIR_NAME = "verbandsliga_2026"
TIMEOUT = 30.0
RETRIES = 3
REQUEST_DELAY = 0.2


def build_league_meta() -> dict[str, Any]:
    return {
        "id": LEAGUE_ID,
        "name": LEAGUE_NAME,
        "acronym": LEAGUE_ACRONYM,
        "season": SEASON,
        "merged": False,
        "source_groups": [
            {"id": LEAGUE_ID, "acronym": LEAGUE_ACRONYM, "name": LEAGUE_NAME}
        ],
        "merge_rules": {
            "teams": "league_entry.id",
            "matches": "match.id",
            "players": "league_entry.id + person.id",
            "standings": "played matches",
        },
    }


def count_played_matches(matches: list[dict[str, Any]]) -> int:
    return sum(
        1
        for match in matches
        if match.get("state") in {"played", "manually_valued"}
        and match.get("home_runs") is not None
        and match.get("away_runs") is not None
    )


def build_combined_payload(
    *,
    generated_at: str,
    teams: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    standings: list[dict[str, Any]],
    batting: list[dict[str, Any]],
    pitching: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "generated_at": generated_at,
        "league": build_league_meta(),
        "counts": {
            "teams": len(teams),
            "matches": len(matches),
            "played_matches": count_played_matches(matches),
            "batters": len(batting),
            "pitchers": len(pitching),
        },
        "teams": teams,
        "matches": matches,
        "standings": standings,
        "batting": batting,
        "pitching": pitching,
    }


def render_report(report: dict[str, Any]) -> str:
    counts = report["counts"]
    lines = [
        "BSM VERBANDSLIGA DATA FETCH REPORT",
        "=" * 76,
        f"Erstellt        : {report['generated_at']}",
        f"Liga            : {LEAGUE_NAME} ({LEAGUE_ACRONYM}, ID {LEAGUE_ID})",
        f"Saison          : {SEASON}",
        f"Mannschaften    : {counts['teams']}",
        f"Spiele          : {counts['matches']}",
        f"Gespielte Spiele: {counts['played_matches']}",
        f"Batter          : {counts['batters']}",
        f"Pitcher         : {counts['pitchers']}",
        "",
        "[MANNSCHAFTEN]",
    ]
    for team in report["teams"]:
        lines.append(
            f"- entry={team['id']} | {team.get('acronym') or '-'} | {team.get('name') or '-'}"
        )
    lines.extend(["", "[TEAM-STATISTIKEN]"])
    for item in report["team_fetches"]:
        marker = "OK" if item.get("ok") else "FEHLER"
        line = (
            f"[{marker}] {item.get('dataset', '-'):<8} "
            f"entry={item.get('league_entry_id')} team={item.get('team')} "
            f"rows={item.get('rows', 0)}"
        )
        if item.get("error"):
            line += f" error={item['error']}"
        lines.append(line)
    lines.extend(["", "[AUSGABE]"])
    lines.extend(f"- {path}" for path in report["output_files"].values())
    lines.append("")
    lines.append("combined.json kann direkt von der Website eingelesen werden.")
    return "\n".join(lines) + "\n"


def run() -> int:
    output_dir = (OUTPUT_ROOT / OUTPUT_DIR_NAME).resolve()
    raw_dir = output_dir / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    group = {"id": LEAGUE_ID, "acronym": LEAGUE_ACRONYM, "name": LEAGUE_NAME}
    print(f"[1/3] {LEAGUE_NAME} ({LEAGUE_ID}) wird geladen …")
    discovery, discovered_teams, failures = fetch_discovery_payloads(
        base_url=BASE_URL,
        league_id=LEAGUE_ID,
        raw_dir=raw_dir / f"{LEAGUE_ACRONYM}_{LEAGUE_ID}",
        timeout=TIMEOUT,
        retries=RETRIES,
        delay=REQUEST_DELAY,
    )

    matches = dedupe_matches(annotate_match_sources(discovery.get("group_matches"), LEAGUE_ID))
    teams = merge_group_teams(
        enrich_discovered_teams(discovered_teams, group),
        extract_match_teams(matches, group),
    )
    standings = compute_combined_standings(matches, teams)
    print(f"      Mannschaften={len(teams)}, Spiele={len(matches)}")

    print("[2/3] Spielerstatistiken werden geladen …")
    batting_rows: list[dict[str, Any]] = []
    pitching_rows: list[dict[str, Any]] = []
    team_fetches: list[dict[str, Any]] = []
    total_requests = len(teams) * 2
    request_no = 0
    for team in teams:
        for dataset in ("batting", "pitching"):
            request_no += 1
            print(f"      [{request_no}/{total_requests}] {team.get('name')} · {dataset}")
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
            if REQUEST_DELAY > 0 and request_no < total_requests:
                time.sleep(REQUEST_DELAY)

    batting_rows = dedupe_player_rows(batting_rows)
    pitching_rows = dedupe_player_rows(pitching_rows)
    generated_at = datetime.now(timezone.utc).isoformat()
    combined = build_combined_payload(
        generated_at=generated_at,
        teams=teams,
        matches=matches,
        standings=standings,
        batting=batting_rows,
        pitching=pitching_rows,
    )
    league_meta = build_league_meta()
    payloads = {
        "teams": {"generated_at": generated_at, "league": league_meta, "teams": teams},
        "matches": {"generated_at": generated_at, "league": league_meta, "matches": matches},
        "standings": {
            "generated_at": generated_at,
            "league": league_meta,
            "note": "Inoffizielle Tabelle aus den veröffentlichten abgeschlossenen Spielen.",
            "standings": standings,
        },
        "batting": {"generated_at": generated_at, "league": league_meta, "players": batting_rows},
        "pitching": {"generated_at": generated_at, "league": league_meta, "players": pitching_rows},
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
        "teams": teams,
        "team_fetches": team_fetches,
        "discovery_failures": failures,
        "output_files": {key: str(path) for key, path in output_files.items()},
    }
    write_json(output_files["fetch_report_json"], report)
    output_files["fetch_report_text"].write_text(render_report(report), encoding="utf-8")

    print("[3/3] Fertig")
    print(f"      {output_files['combined']}")
    print(f"      {output_files['fetch_report_text']}")
    return 0


def main() -> int:
    try:
        return run()
    except KeyboardInterrupt:
        print("\nAusführung abgebrochen.")
        return 130
    except Exception as exc:
        print(f"\nFehler: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
