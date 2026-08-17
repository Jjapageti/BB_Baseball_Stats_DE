#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

SEASON = 2025
UNRESOLVED_STATUSES = {
    "ambiguous",
    "review",
    "unmatched",
    "canonical_scope_missing",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def compact_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def int_value(value: Any) -> int:
    if value in (None, ""):
        return 0
    return int(str(value).strip())


def innings_to_outs(value: Any) -> int:
    raw = str(value or "").strip()
    if not raw:
        return 0

    if "." not in raw:
        return int(raw) * 3

    whole, frac = raw.split(".", 1)
    innings = int(whole or "0")
    partial = int((frac or "0")[:1])

    if partial not in (0, 1, 2):
        raise ValueError(f"Invalid baseball innings value: {value!r}")

    return innings * 3 + partial


def outs_to_innings(outs: int) -> str:
    if outs < 0:
        raise ValueError("Outs cannot be negative")
    return f"{outs // 3}.{outs % 3}"


def canonical_player_key(row: dict[str, Any]) -> str:
    explicit = row.get("player_key")
    if explicit:
        return str(explicit)

    person_id = row.get("person_id")
    if isinstance(person_id, int):
        return f"person:{person_id}"

    raise ValueError(
        "Resolved row has neither player_key nor canonical person_id: "
        f"match_id={row.get('match_id')} raw_name={row.get('raw_name')!r}"
    )


def merge_position_sequence(
    current: list[str],
    incoming: list[str],
) -> list[str]:
    result = list(current)

    for position in incoming:
        token = compact_spaces(str(position)).casefold()
        if not token:
            continue
        if result and result[-1] == token:
            continue
        result.append(token)

    return result


def clean_snapshot(snapshot: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(value)
        for key, value in snapshot.items()
        if value not in (None, "")
    }


def validate_report(report: dict[str, Any]) -> None:
    unresolved_rows = [
        row
        for row in report.get("rows") or []
        if row.get("status") in UNRESOLVED_STATUSES
    ]
    if unresolved_rows:
        counts: dict[str, int] = defaultdict(int)
        for row in unresolved_rows:
            counts[str(row.get("status"))] += 1
        detail = ", ".join(
            f"{status}={count}"
            for status, count in sorted(counts.items())
        )
        raise ValueError(
            "Player match report still contains unresolved rows: " + detail
        )


def _new_log(row: dict[str, Any], player_key: str) -> dict[str, Any]:
    clean_name = (row.get("parsed_name") or {}).get("clean_name")
    return {
        "match_id": row.get("match_id"),
        "match_number": row.get("match_number"),
        "time": row.get("time"),
        "league_ids": list(row.get("league_ids") or []),
        "league_acronyms": list(row.get("league_acronyms") or []),
        "home_team": row.get("home_team"),
        "away_team": row.get("away_team"),
        "boxscore_team": row.get("boxscore_team"),
        "berlin_club_id": row.get("berlin_club_id"),
        "player_key": player_key,
        "person_id": row.get("person_id"),
        "canonical_name": row.get("canonical_name"),
        "boxscore_name": clean_name,
        "identity_status": row.get("status"),
        "identity_source": row.get("identity_source"),
        "identity_assumption": row.get("identity_assumption"),
        "candidate_person_ids": sorted({
            candidate
            for candidate in (row.get("candidate_person_ids") or [])
            if isinstance(candidate, int)
        }),
        "position_sequence": [],
        "batting": None,
        "pitching": None,
        "source_rows": 0,
        "source_raw_names": [],
    }


def _ensure_batting(log: dict[str, Any]) -> dict[str, Any]:
    if log["batting"] is None:
        log["batting"] = {
            "AB": 0,
            "R": 0,
            "H": 0,
            "RBI": 0,
            "K": 0,
            "BB": 0,
            "displayed_cumulative_snapshots": [],
        }
    return log["batting"]


def _ensure_pitching(log: dict[str, Any]) -> dict[str, Any]:
    if log["pitching"] is None:
        log["pitching"] = {
            "IP": "0.0",
            "outs": 0,
            "BF": 0,
            "AB": 0,
            "H": 0,
            "R": 0,
            "ER": 0,
            "K": 0,
            "BB": 0,
            "decision": None,
            "cumulative_record": None,
            "displayed_cumulative_snapshots": [],
        }
    return log["pitching"]


def _merge_identity(log: dict[str, Any], row: dict[str, Any]) -> None:
    candidates = {
        candidate
        for candidate in log.get("candidate_person_ids") or []
        if isinstance(candidate, int)
    }
    candidates.update(
        candidate
        for candidate in row.get("candidate_person_ids") or []
        if isinstance(candidate, int)
    )
    log["candidate_person_ids"] = sorted(candidates)

    row_person_id = row.get("person_id")
    if log.get("person_id") is None and isinstance(row_person_id, int):
        log["person_id"] = row_person_id
        log["canonical_name"] = row.get("canonical_name")

    if row.get("status") == "boxscore_identity":
        log["identity_status"] = "boxscore_identity"
        log["identity_source"] = row.get("identity_source")
        log["identity_assumption"] = row.get("identity_assumption")


def _merge_batting(log: dict[str, Any], row: dict[str, Any]) -> None:
    batting = _ensure_batting(log)
    stats = row.get("stats") or {}

    for key in ("AB", "R", "H", "RBI", "K", "BB"):
        batting[key] += int_value(stats.get(key))

    batting["displayed_cumulative_snapshots"].append(
        clean_snapshot({
            "AVG": stats.get("AVG"),
            "OPS": stats.get("OPS"),
            "raw_name": row.get("raw_name"),
        })
    )

    log["position_sequence"] = merge_position_sequence(
        log["position_sequence"],
        list(row.get("position_sequence") or []),
    )


def _merge_pitching(log: dict[str, Any], row: dict[str, Any]) -> None:
    pitching = _ensure_pitching(log)
    stats = row.get("stats") or {}

    pitching["outs"] += innings_to_outs(stats.get("IP"))
    pitching["IP"] = outs_to_innings(pitching["outs"])

    for key in ("BF", "AB", "H", "R", "ER", "K", "BB"):
        pitching[key] += int_value(stats.get(key))

    decision = row.get("decision")
    cumulative_record = row.get("cumulative_record")
    if decision:
        if pitching["decision"] not in (None, decision):
            raise ValueError(
                "Conflicting pitching decisions for one game/player: "
                f"{pitching['decision']} vs {decision}"
            )
        pitching["decision"] = decision
        pitching["cumulative_record"] = cumulative_record

    pitching["displayed_cumulative_snapshots"].append(
        clean_snapshot({
            "ERA": stats.get("ERA"),
            "raw_name": row.get("raw_name"),
        })
    )


def build_game_logs(report: dict[str, Any]) -> dict[str, Any]:
    validate_report(report)

    season = report.get("season") or SEASON
    grouped: dict[tuple[int, str, str], dict[str, Any]] = {}

    for row in report.get("rows") or []:
        status = row.get("status")
        if status not in {"auto", "boxscore_identity"}:
            continue

        match_id = row.get("match_id")
        if not isinstance(match_id, int):
            raise ValueError(f"Invalid match_id in resolved row: {match_id!r}")

        player_key = canonical_player_key(row)
        team = str(row.get("boxscore_team") or "")
        group_key = (match_id, player_key, team)

        if group_key not in grouped:
            grouped[group_key] = _new_log(row, player_key)

        log = grouped[group_key]
        _merge_identity(log, row)

        raw_name = str(row.get("raw_name") or "")
        if raw_name and raw_name not in log["source_raw_names"]:
            log["source_raw_names"].append(raw_name)
        log["source_rows"] += 1

        role = row.get("role")
        if role == "batting":
            _merge_batting(log, row)
        elif role == "pitching":
            _merge_pitching(log, row)
        else:
            raise ValueError(
                f"Unknown player row role: {role!r} "
                f"(match_id={match_id}, player_key={player_key})"
            )

    logs = list(grouped.values())
    logs.sort(
        key=lambda row: (
            str(row.get("time") or ""),
            int(row.get("match_id") or 0),
            str(row.get("boxscore_team") or "").casefold(),
            str(row.get("player_key") or ""),
        )
    )

    unique_players = {log["player_key"] for log in logs}
    matches = {log["match_id"] for log in logs}
    canonical_logs = sum(
        1 for log in logs if isinstance(log.get("person_id"), int)
    )
    boxscore_identity_logs = sum(
        1 for log in logs if log.get("identity_status") == "boxscore_identity"
    )

    return {
        "schema_version": 1,
        "season": season,
        "source": {
            "type": "player_match_report_v6",
            "note": (
                "Counting stats are aggregated per game. "
                "Displayed AVG/OPS/ERA values are preserved as cumulative "
                "BSM snapshots and are not treated as game rates."
            ),
        },
        "summary": {
            "game_logs": len(logs),
            "matches": len(matches),
            "unique_player_keys": len(unique_players),
            "logs_with_canonical_person_id": canonical_logs,
            "logs_using_boxscore_identity": boxscore_identity_logs,
        },
        "game_logs": logs,
    }


def project_root_candidates(start: Path) -> list[Path]:
    result: list[Path] = []
    for base in [start.resolve(), Path(__file__).resolve().parent]:
        for candidate in [base, *base.parents]:
            if candidate not in result:
                result.append(candidate)
    return result


def discover_project_root() -> Path | None:
    for candidate in project_root_candidates(Path.cwd()):
        if (
            (candidate / "league_data_fetcher.py").exists()
            and (candidate / "data").exists()
        ):
            return candidate
    return None


def discover_report_file(project_root: Path | None) -> Path | None:
    candidates: list[Path] = []

    if project_root:
        candidates.extend([
            project_root
            / "tests"
            / "bsm_season_data"
            / "2025_discovery_v2"
            / "player_match_report_v6.json",
            project_root
            / "bsm_season_data"
            / "2025_discovery_v2"
            / "player_match_report_v6.json",
        ])

    cwd = Path.cwd()
    candidates.extend([
        cwd
        / "bsm_season_data"
        / "2025_discovery_v2"
        / "player_match_report_v6.json",
        cwd / "player_match_report_v6.json",
    ])

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def default_outputs(
    *,
    project_root: Path | None,
    report_file: Path,
) -> tuple[Path, Path]:
    if project_root:
        return (
            project_root / "bsm_season_data" / "2025" / "2025_game_logs.json",
            project_root / "data" / "game_logs" / "2025.json",
        )

    return (
        report_file.parent / "2025_game_logs.json",
        report_file.parent / "2025_game_logs_site.json",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build normalized 2025 Berlin player game logs from "
            "player_match_report_v6.json."
        )
    )
    parser.add_argument("--report-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--site-output", type=Path)
    parser.add_argument(
        "--no-site-copy",
        action="store_true",
        help="Write only the primary game-log JSON.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    project_root = discover_project_root()
    report_file = args.report_file or discover_report_file(project_root)
    if not report_file or not report_file.exists():
        print(
            "ERROR: player_match_report_v6.json not found. "
            "Use --report-file explicitly."
        )
        return 1

    report = load_json(report_file)

    try:
        result = build_game_logs(report)
    except (ValueError, TypeError) as exc:
        print(f"ERROR: {exc}")
        return 1

    default_primary, default_site = default_outputs(
        project_root=project_root,
        report_file=report_file,
    )
    primary = args.output or default_primary
    site = args.site_output or default_site

    save_json(primary, result)
    if not args.no_site_copy:
        save_json(site, result)

    summary = result["summary"]
    print("===== BSM 2025 Berlin Game Logs =====")
    print()
    print(f"Season: {result['season']}")
    print(f"Game logs: {summary['game_logs']}")
    print(f"Matches: {summary['matches']}")
    print(f"Unique player keys: {summary['unique_player_keys']}")
    print(
        "Logs with canonical person_id: "
        f"{summary['logs_with_canonical_person_id']}"
    )
    print(
        "Logs using boxscore identity: "
        f"{summary['logs_using_boxscore_identity']}"
    )
    print()
    print(f"Primary JSON: {primary}")
    if not args.no_site_copy:
        print(f"Site JSON: {site}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
