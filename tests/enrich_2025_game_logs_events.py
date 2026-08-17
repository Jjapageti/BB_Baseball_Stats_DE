from __future__ import annotations

import argparse
import copy
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from bs4 import BeautifulSoup, NavigableString, Tag


SECTION_MAP = {
    "BATTING": "batting",
    "BASERUNNING": "baserunning",
    "FIELDING": "fielding",
}

SUPPORTED_EVENTS = {
    "batting": ("2B", "3B", "HR", "SH", "SF"),
    "baserunning": ("SB", "CS"),
    "fielding": ("E", "PB", "DP", "TP"),
}


def normalize_space(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def accentfold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", normalize_space(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.casefold()


def compact_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", accentfold(value))


def team_key(value: Any) -> str:
    return compact_key(value)


def boxscore_name_key(value: Any) -> str:
    return accentfold(value).rstrip(".")


def parse_event_entry(text: str) -> dict[str, Any]:
    """Parse BSM event notation.

    Examples:
      "Moryson B. (5)"    -> game_count 1, cumulative 5
      "Pfeiffer M. 3 (9)" -> game_count 3, cumulative 9
      "Reinert K."        -> game_count 1, cumulative unknown

    Parentheses are preserved as a cumulative snapshot only when present.
    We do not invent a cumulative total when BSM omits it.
    """
    raw = normalize_space(text).strip(" ,")
    if not raw:
        raise ValueError("empty event entry")

    cumulative_total: int | None = None
    cumulative_match = re.search(r"\s+\((\d+)\)\s*$", raw)
    if cumulative_match:
        cumulative_total = int(cumulative_match.group(1))
        raw = raw[: cumulative_match.start()].rstrip()

    game_count = 1
    game_count_match = re.search(r"\s+(\d+)\s*$", raw)
    if game_count_match:
        game_count = int(game_count_match.group(1))
        raw = raw[: game_count_match.start()].rstrip()

    if not raw:
        raise ValueError(f"missing player name in event entry: {text!r}")

    return {
        "boxscore_name": raw,
        "game_count": game_count,
        "cumulative_total": cumulative_total,
    }


def split_event_entries(value: str) -> list[dict[str, Any]]:
    text = normalize_space(value)
    if not text or text == "---":
        return []

    entries: list[dict[str, Any]] = []
    for part in text.split(","):
        cleaned = normalize_space(part).strip()
        if not cleaned:
            continue
        entries.append(parse_event_entry(cleaned))
    return entries


def batting_team_name(table: Tag) -> str | None:
    first_row = table.find("tr")
    if first_row is None:
        return None

    cells = first_row.find_all(["th", "td"])
    if not cells:
        return None

    header = normalize_space(cells[0].get_text(" ", strip=True))
    match = re.match(r"^(.*?)\s*\(Batters\)\s*$", header, re.IGNORECASE)
    if not match:
        return None
    return normalize_space(match.group(1))


def strings_until_next_table(table: Tag) -> list[str]:
    tokens: list[str] = []

    for element in table.next_elements:
        if element is table:
            continue

        if isinstance(element, Tag) and element.name == "table":
            break

        if not isinstance(element, NavigableString):
            continue

        parent_table = element.parent.find_parent("table") if element.parent else None
        if parent_table is table:
            continue

        text = normalize_space(str(element))
        if text:
            tokens.append(text)

    return tokens


def parse_event_tokens(tokens: Iterable[str]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    result: dict[str, dict[str, list[dict[str, Any]]]] = {
        "batting": {},
        "baserunning": {},
        "fielding": {},
    }

    section: str | None = None
    pending_category: str | None = None

    for raw_token in tokens:
        token = normalize_space(raw_token)
        if not token:
            continue

        upper = token.upper()
        if upper in SECTION_MAP:
            section = SECTION_MAP[upper]
            pending_category = None
            continue

        if section is None:
            continue

        if token == "---":
            pending_category = None
            continue

        combined = re.match(r"^([A-Z0-9]+):\s*(.*)$", token)
        if combined:
            category = combined.group(1).upper()
            value = normalize_space(combined.group(2))
            pending_category = None

            if category not in SUPPORTED_EVENTS.get(section, ()):
                continue
            if value:
                result[section][category] = split_event_entries(value)
            else:
                pending_category = category
            continue

        if pending_category:
            result[section][pending_category] = split_event_entries(token)
            pending_category = None

    return result


def parse_boxscore_event_blocks(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    blocks: list[dict[str, Any]] = []

    for table in soup.find_all("table"):
        team = batting_team_name(table)
        if not team:
            continue

        events = parse_event_tokens(strings_until_next_table(table))
        blocks.append({
            "team": team,
            "events": events,
        })

    return blocks


def team_equivalent(left: str, right: str) -> bool:
    left_key = team_key(left)
    right_key = team_key(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True

    # BSM sometimes uses "Berlin Wizards" in one context and "Wizards" in another.
    def strip_berlin(value: str) -> str:
        return value[6:] if value.startswith("berlin") else value

    return strip_berlin(left_key) == strip_berlin(right_key)


def init_event_fields(log: dict[str, Any]) -> None:
    batting = log.get("batting")
    if isinstance(batting, dict):
        for category in SUPPORTED_EVENTS["batting"]:
            batting.setdefault(category, 0)

    baserunning = log.setdefault("baserunning", {})
    if isinstance(baserunning, dict):
        for category in SUPPORTED_EVENTS["baserunning"]:
            baserunning.setdefault(category, 0)

    fielding = log.setdefault("fielding", {})
    if isinstance(fielding, dict):
        for category in SUPPORTED_EVENTS["fielding"]:
            fielding.setdefault(category, 0)

    log.setdefault("event_cumulative", {
        "batting": {},
        "baserunning": {},
        "fielding": {},
    })


def event_target(log: dict[str, Any], section: str) -> dict[str, Any] | None:
    if section == "batting":
        target = log.get("batting")
        return target if isinstance(target, dict) else None
    target = log.get(section)
    return target if isinstance(target, dict) else None


def candidate_logs_for_entry(
    logs: list[dict[str, Any]],
    *,
    match_id: int,
    team: str,
    boxscore_name: str,
) -> list[dict[str, Any]]:
    name_key = boxscore_name_key(boxscore_name)
    return [
        log
        for log in logs
        if int(log.get("match_id") or -1) == int(match_id)
        and team_equivalent(str(log.get("boxscore_team") or ""), team)
        and boxscore_name_key(log.get("boxscore_name")) == name_key
    ]


def enrich_match_logs(
    logs: list[dict[str, Any]],
    match_id: int,
    blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    report = {
        "match_id": int(match_id),
        "relevant_team_blocks": 0,
        "parsed_entries": 0,
        "assigned_entries": 0,
        "unresolved": [],
    }

    match_logs = [
        log for log in logs
        if int(log.get("match_id") or -1) == int(match_id)
    ]
    if not match_logs:
        return report

    known_teams = [str(log.get("boxscore_team") or "") for log in match_logs]

    for block in blocks:
        block_team = str(block.get("team") or "")
        if not any(team_equivalent(block_team, team) for team in known_teams):
            # Opponent-only block: expected in Berlin-only game logs.
            continue

        report["relevant_team_blocks"] += 1

        team_logs = [
            log for log in match_logs
            if team_equivalent(str(log.get("boxscore_team") or ""), block_team)
        ]
        for log in team_logs:
            init_event_fields(log)

        events = block.get("events") or {}
        for section in ("batting", "baserunning", "fielding"):
            section_events = events.get(section) or {}
            for category, entries in section_events.items():
                if category not in SUPPORTED_EVENTS.get(section, ()):
                    continue

                for entry in entries or []:
                    report["parsed_entries"] += 1
                    candidates = candidate_logs_for_entry(
                        logs,
                        match_id=match_id,
                        team=block_team,
                        boxscore_name=str(entry.get("boxscore_name") or ""),
                    )

                    if len(candidates) != 1:
                        report["unresolved"].append({
                            "match_id": int(match_id),
                            "team": block_team,
                            "section": section,
                            "category": category,
                            "boxscore_name": entry.get("boxscore_name"),
                            "game_count": entry.get("game_count"),
                            "cumulative_total": entry.get("cumulative_total"),
                            "candidate_person_ids": sorted(
                                {
                                    int(candidate["person_id"])
                                    for candidate in candidates
                                    if candidate.get("person_id") is not None
                                }
                            ),
                            "reason": (
                                "no_matching_game_log"
                                if not candidates
                                else "multiple_matching_game_logs"
                            ),
                        })
                        continue

                    log = candidates[0]
                    target = event_target(log, section)
                    if target is None:
                        report["unresolved"].append({
                            "match_id": int(match_id),
                            "team": block_team,
                            "section": section,
                            "category": category,
                            "boxscore_name": entry.get("boxscore_name"),
                            "person_id": log.get("person_id"),
                            "reason": "missing_target_section",
                        })
                        continue

                    target[category] = int(target.get(category) or 0) + int(
                        entry.get("game_count") or 0
                    )

                    cumulative_total = entry.get("cumulative_total")
                    if cumulative_total is not None:
                        cumulative = log.setdefault("event_cumulative", {}).setdefault(
                            section, {}
                        )
                        cumulative[category] = int(cumulative_total)

                    log["event_source"] = "bsm_boxscore_html"
                    report["assigned_entries"] += 1

    return report


def validate_enriched_log(log: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    batting = log.get("batting") or {}

    if isinstance(batting, dict):
        hits = int(batting.get("H") or 0)
        extra_base_hits = sum(
            int(batting.get(category) or 0)
            for category in ("2B", "3B", "HR")
        )
        if extra_base_hits > hits:
            errors.append({
                "code": "extra_base_hits_exceed_hits",
                "match_id": log.get("match_id"),
                "person_id": log.get("person_id"),
                "boxscore_name": log.get("boxscore_name"),
                "H": hits,
                "2B": int(batting.get("2B") or 0),
                "3B": int(batting.get("3B") or 0),
                "HR": int(batting.get("HR") or 0),
            })

    cumulative = log.get("event_cumulative") or {}
    for section, values in cumulative.items():
        target = event_target(log, section)
        if not isinstance(target, dict) or not isinstance(values, dict):
            continue
        for category, cumulative_total in values.items():
            game_count = int(target.get(category) or 0)
            if int(cumulative_total) < game_count:
                errors.append({
                    "code": "cumulative_less_than_game_count",
                    "match_id": log.get("match_id"),
                    "person_id": log.get("person_id"),
                    "boxscore_name": log.get("boxscore_name"),
                    "section": section,
                    "category": category,
                    "game_count": game_count,
                    "cumulative_total": int(cumulative_total),
                })

    return errors


def numeric_match_id(path: Path) -> int | None:
    match = re.search(r"(\d+)", path.stem)
    return int(match.group(1)) if match else None


def raw_html_files(raw_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in raw_dir.iterdir():
        if not path.is_file():
            continue
        if numeric_match_id(path) is None:
            continue
        if path.suffix.lower() in {".html", ".htm", ""}:
            files.append(path)
    return sorted(files, key=lambda path: numeric_match_id(path) or 0)


def find_project_root(start: Path) -> Path:
    candidates = [start.resolve(), *start.resolve().parents]
    for candidate in candidates:
        if (candidate / "data" / "game_logs").exists() and (
            candidate / "tests"
        ).exists():
            return candidate
    raise FileNotFoundError(
        "Projektwurzel nicht gefunden. Das Skript bitte im Projekt oder in tests/ ausführen."
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def enrich_dataset(
    payload: dict[str, Any],
    raw_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    enriched = copy.deepcopy(payload)
    logs = enriched.get("game_logs") or []

    summary = {
        "raw_html_files": 0,
        "event_team_blocks": 0,
        "relevant_team_blocks": 0,
        "parsed_event_entries": 0,
        "assigned_event_entries": 0,
        "unresolved_event_entries": 0,
        "logs_enriched": 0,
        "validation_errors": 0,
    }
    unresolved: list[dict[str, Any]] = []
    match_reports: list[dict[str, Any]] = []

    for html_path in raw_html_files(raw_dir):
        match_id = numeric_match_id(html_path)
        if match_id is None:
            continue

        summary["raw_html_files"] += 1
        html = html_path.read_text(encoding="utf-8", errors="replace")
        blocks = parse_boxscore_event_blocks(html)
        summary["event_team_blocks"] += len(blocks)

        match_report = enrich_match_logs(logs, match_id, blocks)
        summary["relevant_team_blocks"] += match_report["relevant_team_blocks"]
        summary["parsed_event_entries"] += match_report["parsed_entries"]
        summary["assigned_event_entries"] += match_report["assigned_entries"]
        unresolved.extend(match_report["unresolved"])

        if match_report["relevant_team_blocks"] or match_report["unresolved"]:
            match_reports.append(match_report)

    validation_errors: list[dict[str, Any]] = []
    enriched_log_count = 0
    for log in logs:
        if log.get("event_source") == "bsm_boxscore_html":
            enriched_log_count += 1
        validation_errors.extend(validate_enriched_log(log))

    summary["unresolved_event_entries"] = len(unresolved)
    summary["logs_enriched"] = enriched_log_count
    summary["validation_errors"] = len(validation_errors)

    source = enriched.setdefault("source", {})
    note = str(source.get("note") or "")
    addition = (
        " Raw BSM HTML event details (2B/3B/HR/SH/SF, SB/CS, "
        "E/PB/DP/TP) are enriched when a unique canonical game-log player match exists."
    )
    if addition.strip() not in note:
        source["note"] = (note.rstrip() + addition).strip()

    report = {
        "season": enriched.get("season"),
        "summary": summary,
        "unresolved": unresolved,
        "validation_errors": validation_errors,
        "matches": match_reports,
    }
    return enriched, report


def render_report(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "===== BSM Game Log Event Enrichment =====",
        "",
        f"Season: {report.get('season')}",
        f"Raw HTML files: {s['raw_html_files']}",
        f"Event team blocks: {s['event_team_blocks']}",
        f"Berlin-relevant team blocks: {s['relevant_team_blocks']}",
        f"Parsed event entries: {s['parsed_event_entries']}",
        f"Assigned event entries: {s['assigned_event_entries']}",
        f"Unresolved event entries: {s['unresolved_event_entries']}",
        f"Logs enriched: {s['logs_enriched']}",
        f"Validation errors: {s['validation_errors']}",
        "",
        "Notation:",
        "- Name (5) => game_count=1, cumulative_total=5",
        "- Name 2 (5) => game_count=2, cumulative_total=5",
        "- Name => game_count=1, cumulative_total unknown",
        "",
        "No ambiguous short-name event is guessed.",
    ]
    return "\n".join(lines) + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enrich 2025 canonical game logs from saved BSM raw HTML event blocks."
    )
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--game-logs", type=Path)
    parser.add_argument("--primary-output", type=Path)
    parser.add_argument("--site-output", type=Path)
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write enriched game-log JSONs. Without this flag only report/dry-run output is shown.",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()

    project_root = find_project_root(Path.cwd())
    raw_dir = args.raw_dir or (
        project_root
        / "tests"
        / "bsm_season_data"
        / "2025_discovery_v2"
        / "boxscores_html_raw"
    )
    game_logs_path = args.game_logs or (
        project_root / "data" / "game_logs" / "2025.json"
    )
    primary_output = args.primary_output or (
        project_root / "bsm_season_data" / "2025" / "2025_game_logs.json"
    )
    site_output = args.site_output or (
        project_root / "data" / "game_logs" / "2025.json"
    )
    report_dir = args.report_dir or (
        project_root
        / "tests"
        / "bsm_season_data"
        / "2025_discovery_v2"
    )

    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw HTML directory not found: {raw_dir}")
    if not game_logs_path.exists():
        raise FileNotFoundError(f"Game logs JSON not found: {game_logs_path}")

    payload = read_json(game_logs_path)
    enriched, report = enrich_dataset(payload, raw_dir)

    report_json = report_dir / "event_enrichment_report.json"
    report_txt = report_dir / "event_enrichment_report.txt"
    unresolved_json = report_dir / "event_enrichment_unresolved.json"

    write_json(report_json, report)
    write_json(unresolved_json, report["unresolved"])
    report_txt.parent.mkdir(parents=True, exist_ok=True)
    report_txt.write_text(render_report(report), encoding="utf-8")

    print(render_report(report), end="")
    print(f"Report JSON: {report_json}")
    print(f"Report text: {report_txt}")
    print(f"Unresolved JSON: {unresolved_json}")

    if args.write:
        write_json(primary_output, enriched)
        write_json(site_output, enriched)
        print(f"Primary JSON: {primary_output}")
        print(f"Site JSON: {site_output}")
    else:
        print("")
        print("DRY RUN only. Add --write to update the two game-log JSON files.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
