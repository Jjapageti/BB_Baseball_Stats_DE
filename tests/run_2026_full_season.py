#!/usr/bin/env python3
"""2026 BSVBB full-season orchestrator.

Scope
-----
- all BSVBB local leagues discovered through exact Berlin/Brandenburg club IDs
- all overregional competitions containing at least one BSVBB club
- no Boxscore aggregation for season batting/pitching totals

This script deliberately reuses the already-tested project tools:
1. tests/fetch_2025_bsvbb_probe_v2.py --season 2026 --no-boxscores
2. tests/season_data_fetcher.py --season 2026 [--fetch]

The generic season fetcher writes:
- bsm_season_data/2026/season_2026.json
- data/seasons/2026.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

SEASON = 2026

DISCOVERY_RELATIVE = Path("tests") / "bsm_season_data" / "2026_discovery_v2"
SITE_OUTPUT_RELATIVE = Path("data") / "seasons" / "2026.json"

CORE_2026_GROUPS = {
    6205: "VLBB",
    6208: "LLBBDivA",
    6209: "LLBBDivB",
}

# These are historical BSVBB-local competition acronyms.  Passing them to the
# generic season fetcher only corrects the scope label; inclusion does not rely
# on this list because both local_bsvbb and overregional_candidate are fetched.
KNOWN_LOCAL_ACRONYMS = (
    "BzLBB",
    "CoPi",
    "JugA",
    "JugABB",
    "JugBB",
    "JugLLBB",
    "JunBB",
    "JunSB",
    "LLBB",
    "LLBBDivA",
    "LLBBDivB",
    "LLBBPO",
    "SchBB",
    "SchLLBB",
    "SchVLBB",
    "TossBB",
    "VLBB",
    "VLBBPO",
    "VLSB",
)


def _script_path(project_root: Path, filename: str) -> Path:
    candidates = (
        project_root / "tests" / filename,
        project_root / filename,
    )
    for path in candidates:
        if path.exists():
            return path
    # Keep the expected project layout in generated commands so dry unit tests
    # can verify the contract without needing a full repository fixture.
    return candidates[0]


def find_project_root(start: Path | None = None) -> Path:
    """Find BB_Baseball_Stats_DE from cwd or this script's parent chain."""
    seeds = []
    if start is not None:
        seeds.append(start.resolve())
    seeds.append(Path.cwd().resolve())
    script_dir = Path(__file__).resolve().parent
    seeds.extend([script_dir, *script_dir.parents])

    seen: set[Path] = set()
    for seed in seeds:
        for candidate in (seed, *seed.parents):
            if candidate in seen:
                continue
            seen.add(candidate)
            if (
                (candidate / "league_data_fetcher.py").exists()
                and (candidate / "landesliga_data_fetcher_vscode.py").exists()
            ):
                return candidate

    raise FileNotFoundError(
        "BB_Baseball_Stats_DE project root not found. "
        "Run this file inside the repository or pass --project-root."
    )


def build_commands(
    *,
    project_root: Path,
    python_exe: Path,
    fetch: bool,
    local_acronyms: Iterable[str] = KNOWN_LOCAL_ACRONYMS,
) -> list[list[str]]:
    """Build the discovery and season-fetch commands."""
    project_root = project_root.resolve()
    discovery_dir = project_root / DISCOVERY_RELATIVE

    probe_script = _script_path(project_root, "fetch_2025_bsvbb_probe_v2.py")
    season_script = _script_path(project_root, "season_data_fetcher.py")

    discovery_cmd = [
        str(python_exe),
        str(probe_script),
        "--season",
        str(SEASON),
        "--no-boxscores",
        "--output",
        str(discovery_dir),
    ]

    season_cmd = [
        str(python_exe),
        str(season_script),
        "--season",
        str(SEASON),
        "--discovery-dir",
        str(discovery_dir),
    ]

    for acronym in local_acronyms:
        season_cmd.extend(["--local-acronym", str(acronym)])

    if fetch:
        season_cmd.append("--fetch")

    return [discovery_cmd, season_cmd]


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Required file missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {path}: {exc}") from exc


def validate_discovery(discovery_dir: Path) -> dict[str, Any]:
    """Validate 2026 discovery before any full team-stat fetch."""
    league_path = discovery_dir / "candidate_leagues.json"
    match_path = discovery_dir / "candidate_matches.json"

    leagues = _load_json(league_path)
    matches = _load_json(match_path)

    if not isinstance(leagues, list):
        raise TypeError(f"{league_path}: expected a JSON array")
    if not isinstance(matches, list):
        raise TypeError(f"{match_path}: expected a JSON array")
    if not leagues:
        raise ValueError("2026 discovery returned zero candidate leagues.")

    league_ids: set[int] = set()
    scope_counts: dict[str, int] = {}

    for row in leagues:
        if not isinstance(row, dict):
            continue

        raw_id = row.get("league_id")
        try:
            league_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        league_ids.add(league_id)

        scope = str(row.get("scope") or "unknown")
        scope_counts[scope] = scope_counts.get(scope, 0) + 1

    missing_core = sorted(set(CORE_2026_GROUPS) - league_ids)
    if missing_core:
        labels = ", ".join(
            f"{group_id}({CORE_2026_GROUPS[group_id]})"
            for group_id in missing_core
        )
        raise ValueError(
            "2026 discovery is missing already-known core groups: " + labels
        )

    return {
        "league_count": len(leagues),
        "match_count": len(matches),
        "scope_counts": scope_counts,
        "core_group_ids": sorted(set(CORE_2026_GROUPS) & league_ids),
    }


def validate_output(output_path: Path) -> dict[str, Any]:
    """Validate the full-season site payload after --fetch."""
    payload = _load_json(output_path)

    if not isinstance(payload, dict):
        raise TypeError(f"{output_path}: expected a JSON object")
    if payload.get("season") != SEASON:
        raise ValueError(
            f"{output_path}: expected season {SEASON}, got {payload.get('season')!r}"
        )

    scope = payload.get("scope")
    if not isinstance(scope, dict) or scope.get("type") != "bsvbb_full":
        raise ValueError(f"{output_path}: scope.type must be 'bsvbb_full'")

    leagues = payload.get("leagues")
    if not isinstance(leagues, list) or not leagues:
        raise ValueError(f"{output_path}: leagues must be a non-empty array")

    counts = payload.get("counts")
    if not isinstance(counts, dict):
        raise ValueError(f"{output_path}: counts object missing")

    league_count = counts.get("leagues")
    try:
        league_count = int(league_count)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{output_path}: counts.leagues is invalid") from exc

    if league_count <= 0:
        raise ValueError(f"{output_path}: counts.leagues must be > 0")
    if league_count != len(leagues):
        raise ValueError(
            f"{output_path}: counts.leagues={league_count} but "
            f"len(leagues)={len(leagues)}"
        )

    return {
        "season": payload["season"],
        "league_count": league_count,
        "source_group_count": int(counts.get("source_groups") or 0),
        "team_count": int(counts.get("teams") or 0),
        "match_count": int(counts.get("matches") or 0),
        "batter_count": int(counts.get("batters") or 0),
        "pitcher_count": int(counts.get("pitchers") or 0),
    }


def run_command(command: list[str], *, cwd: Path) -> None:
    print()
    print(">", subprocess.list2cmdline(command))
    completed = subprocess.run(command, cwd=str(cwd), check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {completed.returncode}: "
            f"{subprocess.list2cmdline(command)}"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Discover all 2026 BSVBB local + BSVBB-related overregional leagues "
            "and build the season-wide statistics JSON."
        )
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help=(
            "After discovery validation, fetch all team batting/pitching data and "
            "publish data/seasons/2026.json. Without this flag, stop after the "
            "generic season fetcher's dry-run."
        ),
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        help="BB_Baseball_Stats_DE repository root. Usually auto-detected.",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python executable to use for child scripts.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        project_root = (
            args.project_root.resolve()
            if args.project_root is not None
            else find_project_root()
        )

        probe_script = _script_path(project_root, "fetch_2025_bsvbb_probe_v2.py")
        season_script = _script_path(project_root, "season_data_fetcher.py")

        missing = [
            path for path in (probe_script, season_script)
            if not path.exists()
        ]
        if missing:
            raise FileNotFoundError(
                "Required project script(s) missing:\n"
                + "\n".join(f"  - {path}" for path in missing)
            )

        commands = build_commands(
            project_root=project_root,
            python_exe=args.python,
            fetch=args.fetch,
        )

        print("[2026 Full Season]")
        print(f"Project : {project_root}")
        print("Scope   : BSVBB local + BSVBB-related overregional")
        print("Boxscore: NOT used for season batting/pitching totals")

        print("\n[1/3] 2026 league discovery")
        run_command(commands[0], cwd=project_root)

        discovery_dir = project_root / DISCOVERY_RELATIVE
        discovery_summary = validate_discovery(discovery_dir)
        print(
            "Discovery OK: "
            f"{discovery_summary['league_count']} leagues / "
            f"{discovery_summary['match_count']} matches / "
            f"core={discovery_summary['core_group_ids']}"
        )
        print(f"Scopes: {discovery_summary['scope_counts']}")

        print("\n[2/3] Generic season builder")
        run_command(commands[1], cwd=project_root)

        if not args.fetch:
            print()
            print("[DRY-RUN COMPLETE]")
            print("Discovery and logical-league validation succeeded.")
            print("Run again with --fetch to write the full 2026 season dataset.")
            return 0

        print("\n[3/3] Final site JSON validation")
        output_path = project_root / SITE_OUTPUT_RELATIVE
        output_summary = validate_output(output_path)
        print(
            "2026 season JSON OK: "
            f"leagues={output_summary['league_count']} "
            f"source_groups={output_summary['source_group_count']} "
            f"teams={output_summary['team_count']} "
            f"matches={output_summary['match_count']} "
            f"batters={output_summary['batter_count']} "
            f"pitchers={output_summary['pitcher_count']}"
        )
        print(f"Output: {output_path}")
        return 0

    except KeyboardInterrupt:
        print("\nAborted.")
        return 130
    except Exception as exc:
        print(f"\nERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
