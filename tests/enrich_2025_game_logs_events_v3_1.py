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

    # BSM occasionally publishes an impossible cumulative snapshot, e.g.
    # "Name 3 (2)": three events in this game but cumulative total two.
    # Preserve the game count and discard only the contradictory cumulative
    # value so it cannot poison cumulative-chain resolution or validation.
    if (
        cumulative_total is not None
        and cumulative_total < game_count
    ):
        cumulative_total = None

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


def event_context_from_candidates(
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    if not candidates:
        return {"time": None, "league_id": None, "club_id": None}

    first = candidates[0]
    league_ids = first.get("league_ids") or []
    return {
        "time": first.get("time"),
        "league_id": int(league_ids[0]) if league_ids else None,
        "club_id": (
            int(first["berlin_club_id"])
            if first.get("berlin_club_id") is not None
            else None
        ),
    }


def apply_event_assignment(
    log: dict[str, Any],
    event: dict[str, Any],
) -> bool:
    init_event_fields(log)
    section = str(event.get("section") or "")
    category = str(event.get("category") or "")
    target = event_target(log, section)
    if target is None:
        return False

    target[category] = int(target.get(category) or 0) + int(
        event.get("game_count") or 0
    )

    cumulative_total = event.get("cumulative_total")
    if cumulative_total is not None:
        cumulative = log.setdefault("event_cumulative", {}).setdefault(
            section, {}
        )
        cumulative[category] = int(cumulative_total)

    log["event_source"] = "bsm_boxscore_html"
    return True


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
        "assigned_observations": [],
        "unresolved": [],
    }

    match_logs = [
        log for log in logs
        if int(log.get("match_id") or -1) == int(match_id)
    ]
    if not match_logs:
        return report

    known_teams = [str(log.get("boxscore_team") or "") for log in match_logs]
    event_index = 0

    for block_index, block in enumerate(blocks):
        block_team = str(block.get("team") or "")
        if not any(team_equivalent(block_team, team) for team in known_teams):
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

                for entry_in_category, entry in enumerate(entries or []):
                    report["parsed_entries"] += 1
                    event_index += 1
                    event_id = (
                        f"{int(match_id)}:{block_index}:{section}:"
                        f"{category}:{entry_in_category}:{event_index}"
                    )

                    candidates = candidate_logs_for_entry(
                        logs,
                        match_id=match_id,
                        team=block_team,
                        boxscore_name=str(entry.get("boxscore_name") or ""),
                    )
                    context = event_context_from_candidates(candidates)

                    observation = {
                        "event_id": event_id,
                        "match_id": int(match_id),
                        "team": block_team,
                        "section": section,
                        "category": category,
                        "boxscore_name": entry.get("boxscore_name"),
                        "game_count": int(entry.get("game_count") or 0),
                        "cumulative_total": entry.get("cumulative_total"),
                        "candidate_person_ids": sorted(
                            {
                                int(candidate["person_id"])
                                for candidate in candidates
                                if candidate.get("person_id") is not None
                            }
                        ),
                        **context,
                    }

                    if len(candidates) != 1:
                        observation["reason"] = (
                            "no_matching_game_log"
                            if not candidates
                            else "multiple_matching_game_logs"
                        )
                        report["unresolved"].append(observation)
                        continue

                    log = candidates[0]
                    observation["fixed_person_id"] = int(log["person_id"])

                    if not apply_event_assignment(log, observation):
                        observation["person_id"] = log.get("person_id")
                        observation["reason"] = "missing_target_section"
                        report["unresolved"].append(observation)
                        continue

                    report["assigned_observations"].append(observation)
                    report["assigned_entries"] += 1

    return report


def matching_event_logs(
    logs: list[dict[str, Any]],
    event: dict[str, Any],
) -> list[dict[str, Any]]:
    candidate_ids = {
        int(value)
        for value in event.get("candidate_person_ids") or []
        if value is not None
    }

    candidates = candidate_logs_for_entry(
        logs,
        match_id=int(event.get("match_id") or -1),
        team=str(event.get("team") or ""),
        boxscore_name=str(event.get("boxscore_name") or ""),
    )

    if candidate_ids:
        candidates = [
            log for log in candidates
            if log.get("person_id") is not None
            and int(log["person_id"]) in candidate_ids
        ]
    return candidates


def eligible_person_ids_for_event(
    logs: list[dict[str, Any]],
    event: dict[str, Any],
) -> list[int]:
    section = str(event.get("section") or "")
    category = str(event.get("category") or "")
    game_count = int(event.get("game_count") or 0)

    eligible: list[int] = []
    for log in matching_event_logs(logs, event):
        person_id = log.get("person_id")
        if person_id is None:
            continue

        if section == "batting":
            batting = log.get("batting")
            if not isinstance(batting, dict):
                continue
            if category in {"2B", "3B", "HR"}:
                if int(batting.get("H") or 0) < game_count:
                    continue

        elif section == "baserunning":
            # A runner recorded in the BSM batter block should have a batting
            # game-log row, even if AB=0 (pinch runner / walk / substitution).
            if not isinstance(log.get("batting"), dict):
                continue

        elif section == "fielding" and category == "PB":
            positions = {
                str(position).lower()
                for position in log.get("position_sequence") or []
            }
            if "c" not in positions:
                continue

        eligible.append(int(person_id))

    return sorted(set(eligible))


def event_chain_key(event: dict[str, Any]) -> tuple[Any, ...] | None:
    league_id = event.get("league_id")
    club_id = event.get("club_id")
    if league_id is None or club_id is None:
        return None
    return (
        int(league_id),
        int(club_id),
        boxscore_name_key(event.get("boxscore_name")),
        str(event.get("section") or ""),
        str(event.get("category") or ""),
    )


def event_sort_key(event: dict[str, Any]) -> tuple[str, int, str]:
    return (
        str(event.get("time") or ""),
        int(event.get("match_id") or -1),
        str(event.get("event_id") or ""),
    )


def enumerate_chain_solutions(
    events: list[dict[str, Any]],
    logs: list[dict[str, Any]],
    *,
    max_solutions: int = 20000,
) -> list[dict[str, int]]:
    if not events:
        return []

    prepared: list[dict[str, Any]] = []
    for source in events:
        event = dict(source)
        fixed = event.get("fixed_person_id")
        if fixed is not None:
            choices = [int(fixed)]
        else:
            choices = eligible_person_ids_for_event(logs, event)

        if not choices:
            return []

        event["_choices"] = choices
        prepared.append(event)

    prepared.sort(key=event_sort_key)

    by_match: dict[int, list[dict[str, Any]]] = defaultdict(list)
    match_order: list[int] = []
    for event in prepared:
        match_id = int(event.get("match_id") or -1)
        if match_id not in by_match:
            match_order.append(match_id)
        by_match[match_id].append(event)

    solutions: list[dict[str, int]] = []
    overflow = False

    def enumerate_match_assignments(
        match_events: list[dict[str, Any]],
    ) -> list[dict[str, int]]:
        assignments: list[dict[str, int]] = []

        def rec(
            index: int,
            used_people: set[int],
            current: dict[str, int],
        ) -> None:
            if index >= len(match_events):
                assignments.append(dict(current))
                return

            event = match_events[index]
            event_id = str(event["event_id"])
            for person_id in event["_choices"]:
                # BSM aggregates one category into one entry per player/game.
                if person_id in used_people:
                    continue
                used_people.add(person_id)
                current[event_id] = person_id
                rec(index + 1, used_people, current)
                current.pop(event_id, None)
                used_people.remove(person_id)

        rec(0, set(), {})
        return assignments

    def rec_matches(
        match_index: int,
        running_totals: dict[int, int],
        assignments: dict[str, int],
    ) -> None:
        nonlocal overflow
        if overflow:
            return

        if match_index >= len(match_order):
            solutions.append(dict(assignments))
            if len(solutions) > max_solutions:
                overflow = True
            return

        match_id = match_order[match_index]
        match_events = by_match[match_id]

        for match_assignment in enumerate_match_assignments(match_events):
            new_totals = dict(running_totals)
            valid = True

            for event in match_events:
                event_id = str(event["event_id"])
                person_id = int(match_assignment[event_id])
                new_totals[person_id] = (
                    int(new_totals.get(person_id, 0))
                    + int(event.get("game_count") or 0)
                )

            # Parenthesized BSM values are interpreted as the cumulative total
            # immediately after this game in this league/team/category chain.
            for event in match_events:
                cumulative_total = event.get("cumulative_total")
                if cumulative_total is None:
                    continue
                person_id = int(match_assignment[str(event["event_id"])])
                if int(new_totals.get(person_id, 0)) != int(cumulative_total):
                    valid = False
                    break

            if not valid:
                continue

            assignments.update(match_assignment)
            rec_matches(match_index + 1, new_totals, assignments)
            for event_id in match_assignment:
                assignments.pop(event_id, None)

    rec_matches(0, {}, {})

    if overflow:
        # Never infer consensus from a truncated solution set.
        return []
    return solutions


def solve_event_chain_group(
    events: list[dict[str, Any]],
    logs: list[dict[str, Any]],
) -> dict[str, int]:
    solutions = enumerate_chain_solutions(events, logs)
    if not solutions:
        return {}

    resolved: dict[str, int] = {}
    event_ids = {
        str(event["event_id"])
        for event in events
        if event.get("fixed_person_id") is None
    }

    for event_id in event_ids:
        assigned_people = {
            int(solution[event_id])
            for solution in solutions
            if event_id in solution
        }
        if len(assigned_people) == 1:
            resolved[event_id] = next(iter(assigned_people))

    return resolved


def event_log_for_person(
    logs: list[dict[str, Any]],
    event: dict[str, Any],
    person_id: int,
) -> dict[str, Any] | None:
    for log in matching_event_logs(logs, event):
        if log.get("person_id") is not None and int(log["person_id"]) == int(person_id):
            return log
    return None


def resolved_observation(
    event: dict[str, Any],
    person_id: int,
    method: str,
) -> dict[str, Any]:
    result = dict(event)
    result.pop("reason", None)
    result["fixed_person_id"] = int(person_id)
    result["resolved_person_id"] = int(person_id)
    result["resolution_method"] = method
    return result


def resolve_ambiguous_events(
    logs: list[dict[str, Any]],
    assigned_observations: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    methods = {
        "resolved_by_hard_constraints": 0,
        "resolved_by_cumulative_chain": 0,
    }
    resolved: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []
    chain_observations = [dict(item) for item in assigned_observations]

    # Pass 1: local game evidence.
    for source in unresolved:
        event = dict(source)
        if event.get("reason") != "multiple_matching_game_logs":
            remaining.append(event)
            continue

        eligible = eligible_person_ids_for_event(logs, event)
        event["eligible_person_ids"] = eligible

        if len(eligible) == 1:
            person_id = eligible[0]
            log = event_log_for_person(logs, event, person_id)
            if log is not None and apply_event_assignment(log, event):
                item = resolved_observation(
                    event,
                    person_id,
                    "hard_constraint",
                )
                resolved.append(item)
                chain_observations.append(item)
                methods["resolved_by_hard_constraints"] += 1
                continue

        # Keep only hard-eligible candidates for the chain solver when the
        # filter leaves at least one candidate. If all were filtered, preserve
        # the original candidate set rather than treating the heuristic as proof.
        if eligible:
            event["candidate_person_ids"] = eligible
        remaining.append(event)

    # Pass 2: exact cumulative chains inside one league/team/category.
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for event in chain_observations:
        key = event_chain_key(event)
        if key is not None:
            groups[key].append(event)
    for event in remaining:
        if event.get("reason") != "multiple_matching_game_logs":
            continue
        key = event_chain_key(event)
        if key is not None:
            groups[key].append(event)

    chain_resolutions: dict[str, int] = {}
    for events in groups.values():
        if not any(
            event.get("fixed_person_id") is None
            for event in events
        ):
            continue
        chain_resolutions.update(solve_event_chain_group(events, logs))

    next_remaining: list[dict[str, Any]] = []
    for event in remaining:
        event_id = str(event.get("event_id") or "")
        person_id = chain_resolutions.get(event_id)
        if person_id is None:
            next_remaining.append(event)
            continue

        log = event_log_for_person(logs, event, person_id)
        if log is None or not apply_event_assignment(log, event):
            next_remaining.append(event)
            continue

        item = resolved_observation(
            event,
            person_id,
            "cumulative_chain",
        )
        resolved.append(item)
        methods["resolved_by_cumulative_chain"] += 1

    return resolved, next_remaining, methods


SOFTBALL_ACRONYMS = {
    "VLSB",
    "BLDN",
    "BLDDP",
    "BLDS",
}


def is_softball_acronym(value: Any) -> bool:
    raw = normalize_space(value).upper()
    if not raw:
        return False
    if raw in SOFTBALL_ACRONYMS:
        return True
    return "SB" in raw


def match_league_acronyms(
    logs: list[dict[str, Any]],
    match_id: int,
    team: str | None = None,
) -> list[str]:
    acronyms: list[str] = []
    for log in logs:
        if int(log.get("match_id") or -1) != int(match_id):
            continue
        if team and not team_equivalent(str(log.get("boxscore_team") or ""), team):
            continue
        for acronym in log.get("league_acronyms") or []:
            value = normalize_space(acronym)
            if value and value not in acronyms:
                acronyms.append(value)
    if acronyms or not team:
        return acronyms

    # If an event player has no game-log row, still recover match-level league context.
    return match_league_acronyms(logs, match_id, None)


def mark_fielding_event_unknown(
    logs: list[dict[str, Any]],
    event: dict[str, Any],
) -> None:
    if str(event.get("section") or "") != "fielding":
        return

    category = str(event.get("category") or "")
    if not category:
        return

    for log in matching_event_logs(logs, event):
        fielding = log.setdefault("fielding", {})
        if isinstance(fielding, dict):
            fielding[category] = None
            log["event_source"] = "bsm_boxscore_html"


def classify_ignored_fielding_events(
    logs: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ignored: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []

    for source in unresolved:
        event = dict(source)

        if str(event.get("section") or "") != "fielding":
            remaining.append(source)
            continue

        reason = str(event.get("reason") or "")
        match_id = int(event.get("match_id") or -1)
        team = str(event.get("team") or "")

        if reason == "no_matching_game_log":
            event["ignore_reason"] = "fielding_only_no_game_log"
            event["league_acronyms"] = match_league_acronyms(
                logs, match_id, team
            )
            ignored.append(event)
            continue

        if reason == "multiple_matching_game_logs":
            # Any unresolved fielding event means the candidates' zero values
            # would be false certainty. Preserve explicit unknown instead.
            mark_fielding_event_unknown(logs, event)

            acronyms = match_league_acronyms(logs, match_id, team)
            if any(is_softball_acronym(value) for value in acronyms):
                event["ignore_reason"] = "softball_ambiguous_fielding"
                event["league_acronyms"] = acronyms
                ignored.append(event)
                continue

        remaining.append(event)

    return ignored, remaining


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



FINAL_TOTAL_EVENT_MAP = {
    "2B": "doubles",
    "3B": "triples",
    "HR": "homeruns",
    "SB": "stolen_bases",
    "CS": "caught_stealings",
    "SH": "sacrifice_hits",
    "SF": "sacrifice_flys",
}


def build_canonical_batting_scopes(
    season_payload: dict[str, Any],
) -> dict[int, list[dict[str, Any]]]:
    scopes: dict[int, list[dict[str, Any]]] = defaultdict(list)

    for league in season_payload.get("leagues") or []:
        league_source_group_ids = {
            int(source["id"])
            for source in league.get("source_groups") or []
            if isinstance(source, dict) and source.get("id") is not None
        }

        for row in league.get("batting") or []:
            if not isinstance(row, dict):
                continue
            person = row.get("person") or {}
            person_id = person.get("id")
            if person_id is None:
                continue

            values = row.get("values") or {}
            league_entry = row.get("league_entry") or {}
            group_ids = {
                int(group_id)
                for group_id in league_entry.get("group_ids") or []
                if group_id is not None
            }
            if not group_ids:
                group_ids = set(league_source_group_ids)
            if not group_ids:
                continue

            totals = {
                event_category: int(values.get(stat_field) or 0)
                for event_category, stat_field in FINAL_TOTAL_EVENT_MAP.items()
            }
            scopes[int(person_id)].append({
                "person_id": int(person_id),
                "group_ids": sorted(group_ids),
                "games": int(values.get("games") or 0),
                "totals": totals,
                "league_entry_id": league_entry.get("id"),
                "league_context_key": (row.get("league_context") or {}).get("key")
                    or league.get("key"),
                "league_name": (row.get("league_context") or {}).get("name")
                    or league.get("name"),
            })

    return scopes


def find_canonical_batting_scope(
    scopes: dict[int, list[dict[str, Any]]],
    person_id: int,
    league_id: int,
) -> dict[str, Any] | None:
    matches = [
        scope
        for scope in scopes.get(int(person_id), [])
        if int(league_id) in {int(value) for value in scope.get("group_ids") or []}
    ]
    return matches[0] if len(matches) == 1 else None


def canonical_scope_has_complete_game_coverage(
    scope: dict[str, Any],
    logs: list[dict[str, Any]],
) -> bool:
    if not scope:
        return False

    person_id = int(scope["person_id"])
    group_ids = {int(value) for value in scope.get("group_ids") or []}
    match_ids = {
        int(log["match_id"])
        for log in logs
        if log.get("person_id") is not None
        and int(log["person_id"]) == person_id
        and isinstance(log.get("batting"), dict)
        and group_ids.intersection(
            {
                int(value)
                for value in log.get("league_ids") or []
                if value is not None
            }
        )
        and log.get("match_id") is not None
    }
    return len(match_ids) == int(scope.get("games") or 0)


def event_assigned_person_id(event: dict[str, Any]) -> int | None:
    for field in ("resolved_person_id", "fixed_person_id", "person_id"):
        value = event.get(field)
        if value is not None:
            return int(value)
    return None


def assigned_event_total_for_scope(
    assigned_events: list[dict[str, Any]],
    scope: dict[str, Any],
    category: str,
) -> int:
    person_id = int(scope["person_id"])
    group_ids = {int(value) for value in scope.get("group_ids") or []}
    total = 0

    for event in assigned_events:
        if str(event.get("category") or "") != category:
            continue
        if event_assigned_person_id(event) != person_id:
            continue
        league_id = event.get("league_id")
        if league_id is None or int(league_id) not in group_ids:
            continue
        total += int(event.get("game_count") or 0)

    return total


def season_total_event_group_key(
    event: dict[str, Any],
    scopes: dict[int, list[dict[str, Any]]],
) -> tuple[Any, ...] | None:
    section = str(event.get("section") or "")
    category = str(event.get("category") or "")
    if category not in FINAL_TOTAL_EVENT_MAP or section not in {"batting", "baserunning"}:
        return None

    league_id = event.get("league_id")
    if league_id is None:
        return None

    candidate_ids = [
        int(value)
        for value in (
            event.get("eligible_person_ids")
            or event.get("candidate_person_ids")
            or []
        )
        if value is not None
    ]
    if not candidate_ids:
        return None

    candidate_scopes = [
        find_canonical_batting_scope(scopes, person_id, int(league_id))
        for person_id in candidate_ids
    ]
    if any(scope is None for scope in candidate_scopes):
        return None

    merged_group_ids = sorted({
        int(group_id)
        for scope in candidate_scopes
        if scope is not None
        for group_id in scope.get("group_ids") or []
    })
    return (
        section,
        category,
        boxscore_name_key(event.get("boxscore_name")),
        tuple(merged_group_ids),
    )


def enumerate_season_total_solutions(
    events: list[dict[str, Any]],
    logs: list[dict[str, Any]],
    scopes: dict[int, list[dict[str, Any]]],
    assigned_events: list[dict[str, Any]],
    *,
    max_solutions: int = 20000,
) -> list[dict[str, int]]:
    prepared: list[dict[str, Any]] = []
    candidate_scope_by_event: dict[str, dict[int, dict[str, Any]]] = {}

    for source in events:
        event = dict(source)
        section = str(event.get("section") or "")
        category = str(event.get("category") or "")
        league_id = event.get("league_id")
        if (
            category not in FINAL_TOTAL_EVENT_MAP
            or section not in {"batting", "baserunning"}
            or league_id is None
        ):
            return []

        candidates = [
            int(value)
            for value in (
                event.get("eligible_person_ids")
                or event.get("candidate_person_ids")
                or []
            )
            if value is not None
        ]
        if not candidates:
            return []

        event_scopes: dict[int, dict[str, Any]] = {}
        for person_id in candidates:
            scope = find_canonical_batting_scope(scopes, person_id, int(league_id))
            if scope is None or not canonical_scope_has_complete_game_coverage(scope, logs):
                # If even one original candidate lacks complete coverage, final totals
                # cannot safely exclude that person.
                return []
            event_scopes[person_id] = scope

        event["_choices"] = sorted(event_scopes)
        prepared.append(event)
        candidate_scope_by_event[str(event["event_id"])] = event_scopes

    if not prepared:
        return []

    prepared.sort(key=event_sort_key)
    solutions: list[dict[str, int]] = []
    overflow = False

    # Precompute fixed totals from v1/v2 assignments for each candidate scope/category.
    base_totals: dict[tuple[int, tuple[int, ...], str], int] = {}
    final_totals: dict[tuple[int, tuple[int, ...], str], int] = {}
    for event in prepared:
        category = str(event["category"])
        event_id = str(event["event_id"])
        for person_id, scope in candidate_scope_by_event[event_id].items():
            scope_key = (
                int(person_id),
                tuple(sorted(int(v) for v in scope.get("group_ids") or [])),
                category,
            )
            if scope_key not in base_totals:
                base_totals[scope_key] = assigned_event_total_for_scope(
                    assigned_events, scope, category
                )
                final_totals[scope_key] = int(
                    (scope.get("totals") or {}).get(category) or 0
                )

    def rec(
        index: int,
        assignment: dict[str, int],
        added_totals: dict[tuple[int, tuple[int, ...], str], int],
        used_by_match: dict[tuple[int, str], set[int]],
    ) -> None:
        nonlocal overflow
        if overflow:
            return

        if index >= len(prepared):
            for scope_key, base in base_totals.items():
                if base + int(added_totals.get(scope_key, 0)) != final_totals[scope_key]:
                    return
            solutions.append(dict(assignment))
            if len(solutions) > max_solutions:
                overflow = True
            return

        event = prepared[index]
        event_id = str(event["event_id"])
        category = str(event["category"])
        match_id = int(event.get("match_id") or -1)
        same_game_key = (match_id, category)

        for person_id in event["_choices"]:
            used = used_by_match.setdefault(same_game_key, set())
            if person_id in used:
                continue

            scope = candidate_scope_by_event[event_id][person_id]
            scope_key = (
                int(person_id),
                tuple(sorted(int(v) for v in scope.get("group_ids") or [])),
                category,
            )
            new_added = int(added_totals.get(scope_key, 0)) + int(
                event.get("game_count") or 0
            )
            if base_totals[scope_key] + new_added > final_totals[scope_key]:
                continue

            assignment[event_id] = person_id
            old_added = added_totals.get(scope_key)
            added_totals[scope_key] = new_added
            used.add(person_id)

            rec(index + 1, assignment, added_totals, used_by_match)

            used.remove(person_id)
            if not used:
                used_by_match.pop(same_game_key, None)
            if old_added is None:
                added_totals.pop(scope_key, None)
            else:
                added_totals[scope_key] = old_added
            assignment.pop(event_id, None)

    rec(0, {}, {}, {})
    return [] if overflow else solutions


def resolve_by_season_final_totals(
    logs: list[dict[str, Any]],
    season_payload: dict[str, Any],
    assigned_events: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    scopes = build_canonical_batting_scopes(season_payload)
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    passthrough: list[dict[str, Any]] = []

    for source in unresolved:
        event = dict(source)
        if event.get("reason") != "multiple_matching_game_logs":
            passthrough.append(event)
            continue

        key = season_total_event_group_key(event, scopes)
        if key is None:
            passthrough.append(event)
            continue
        groups[key].append(event)

    resolved: list[dict[str, Any]] = []
    remaining_group_events: list[dict[str, Any]] = []

    for events in groups.values():
        solutions = enumerate_season_total_solutions(
            events,
            logs,
            scopes,
            assigned_events,
        )
        if not solutions:
            remaining_group_events.extend(events)
            continue

        event_ids = [str(event["event_id"]) for event in events]
        consensus: dict[str, int] = {}
        for event_id in event_ids:
            people = {
                int(solution[event_id])
                for solution in solutions
                if event_id in solution
            }
            if len(people) == 1:
                consensus[event_id] = next(iter(people))

        for event in events:
            event_id = str(event["event_id"])
            person_id = consensus.get(event_id)
            if person_id is None:
                remaining_group_events.append(event)
                continue

            log = event_log_for_person(logs, event, person_id)
            if log is None or not apply_event_assignment(log, event):
                remaining_group_events.append(event)
                continue

            item = resolved_observation(
                event,
                person_id,
                "season_final_total",
            )
            resolved.append(item)
            assigned_events.append(item)

    remaining = passthrough + remaining_group_events
    remaining.sort(key=lambda item: str(item.get("event_id") or ""))
    return resolved, remaining



def prepare_logs_for_event_enrichment(
    logs: list[dict[str, Any]],
) -> None:
    """Remove only event fields previously generated by this enricher.

    This makes repeated dry-run/write cycles idempotent without touching
    canonical batting/pitching data from the v8 game-log builder.
    """
    for log in logs:
        if log.get("event_source") != "bsm_boxscore_html":
            continue

        batting = log.get("batting")
        if isinstance(batting, dict):
            for category in SUPPORTED_EVENTS["batting"]:
                batting.pop(category, None)

        log.pop("baserunning", None)
        log.pop("fielding", None)
        log.pop("event_cumulative", None)
        log.pop("event_source", None)


def enrich_dataset(
    payload: dict[str, Any],
    raw_dir: Path,
    season_payload: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    enriched = copy.deepcopy(payload)
    logs = enriched.get("game_logs") or []
    prepare_logs_for_event_enrichment(logs)

    summary = {
        "raw_html_files": 0,
        "event_team_blocks": 0,
        "relevant_team_blocks": 0,
        "parsed_event_entries": 0,
        "assigned_event_entries_v1": 0,
        "initial_unresolved_event_entries": 0,
        "resolved_by_hard_constraints": 0,
        "resolved_by_cumulative_chain": 0,
        "resolved_by_season_final_totals": 0,
        "assigned_event_entries": 0,
        "unresolved_event_entries": 0,
        "logs_enriched": 0,
        "validation_errors": 0,
    }
    unresolved: list[dict[str, Any]] = []
    assigned_observations: list[dict[str, Any]] = []
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
        summary["assigned_event_entries_v1"] += match_report["assigned_entries"]
        unresolved.extend(match_report["unresolved"])
        assigned_observations.extend(match_report["assigned_observations"])

        if match_report["relevant_team_blocks"] or match_report["unresolved"]:
            match_reports.append({
                key: value
                for key, value in match_report.items()
                if key != "assigned_observations"
            })

    summary["initial_unresolved_event_entries"] = len(unresolved)

    resolved_v2, unresolved_v2, methods = resolve_ambiguous_events(
        logs,
        assigned_observations,
        unresolved,
    )
    summary.update(methods)

    resolved_v3: list[dict[str, Any]] = []
    unresolved_v3 = unresolved_v2
    if season_payload is not None:
        resolved_v3, unresolved_v3 = resolve_by_season_final_totals(
            logs,
            season_payload,
            assigned_observations + resolved_v2,
            unresolved_v2,
        )

    ignored_v31, unresolved_v31 = classify_ignored_fielding_events(
        logs,
        unresolved_v3,
    )

    summary["resolved_by_season_final_totals"] = len(resolved_v3)
    summary["ignored_fielding_events"] = len(ignored_v31)
    summary["ignored_softball_ambiguous_fielding"] = sum(
        1
        for item in ignored_v31
        if item.get("ignore_reason") == "softball_ambiguous_fielding"
    )
    summary["ignored_fielding_only_no_game_log"] = sum(
        1
        for item in ignored_v31
        if item.get("ignore_reason") == "fielding_only_no_game_log"
    )
    summary["assigned_event_entries"] = (
        summary["assigned_event_entries_v1"]
        + len(resolved_v2)
        + len(resolved_v3)
    )
    summary["unresolved_event_entries"] = len(unresolved_v31)

    validation_errors: list[dict[str, Any]] = []
    enriched_log_count = 0
    for log in logs:
        if log.get("event_source") == "bsm_boxscore_html":
            enriched_log_count += 1
        validation_errors.extend(validate_enriched_log(log))

    summary["logs_enriched"] = enriched_log_count
    summary["validation_errors"] = len(validation_errors)

    source = enriched.setdefault("source", {})
    note = str(source.get("note") or "")
    addition = (
        " Raw BSM HTML event details (2B/3B/HR/SH/SF, SB/CS, "
        "E/PB/DP/TP) are enriched when a canonical game-log player can be "
        "resolved uniquely. v3 uses game-stat hard constraints, exact "
        "league/team cumulative event chains, and complete-coverage canonical "
        "season final totals for 2B/3B/HR/SB/CS/SH/SF."
    )
    if addition.strip() not in note:
        source["note"] = (note.rstrip() + addition).strip()

    report = {
        "season": enriched.get("season"),
        "summary": summary,
        "resolved_v2": resolved_v2,
        "resolved_v3": resolved_v3,
        "ignored_v3_1": ignored_v31,
        "unresolved": unresolved_v31,
        "validation_errors": validation_errors,
        "matches": match_reports,
    }
    return enriched, report

def render_report(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "===== BSM Game Log Event Enrichment v3.1 =====",
        "",
        f"Season: {report.get('season')}",
        f"Raw HTML files: {s['raw_html_files']}",
        f"Event team blocks: {s['event_team_blocks']}",
        f"Berlin-relevant team blocks: {s['relevant_team_blocks']}",
        f"Parsed event entries: {s['parsed_event_entries']}",
        f"Initially assigned entries: {s['assigned_event_entries_v1']}",
        f"Initial unresolved entries: {s['initial_unresolved_event_entries']}",
        f"Resolved by hard constraints: {s['resolved_by_hard_constraints']}",
        f"Resolved by cumulative chain: {s['resolved_by_cumulative_chain']}",
        f"Resolved by season final totals: {s['resolved_by_season_final_totals']}",
        f"Ignored fielding events: {s.get('ignored_fielding_events', 0)}",
        f"  - Softball ambiguous fielding: {s.get('ignored_softball_ambiguous_fielding', 0)}",
        f"  - Fielding-only / no game log: {s.get('ignored_fielding_only_no_game_log', 0)}",
        f"Assigned event entries final: {s['assigned_event_entries']}",
        f"Unresolved event entries final: {s['unresolved_event_entries']}",
        f"Logs enriched: {s['logs_enriched']}",
        f"Validation errors: {s['validation_errors']}",
        "",
        "v3 evidence rules:",
        "- 2B/3B/HR cannot exceed that player's game H.",
        "- baserunning events require a batting game-log row.",
        "- PB requires catcher position when short-name candidates collide.",
        "- parenthesized cumulative totals must form an exact chronological",
        "  chain inside the same league / Berlin club / event category.",
        "- same player cannot receive two separate entries of the same",
        "  category in one game because BSM aggregates the game count.",
        "- final 2B/3B/HR/SB/CS/SH/SF totals are used only when each",
        "  candidate's canonical games count exactly matches available game logs",
        "  for that canonical league scope; otherwise the constraint is skipped.",
        "- fielding E/PB/DP/TP are never inferred from batting final totals.",
        "- unresolved softball fielding is classified as ignored for the current",
        "  batting/pitching site scope; ambiguous candidate values are stored as null.",
        "- fielding-only events with no canonical game-log row are ignored, not synthesized.",
        "",
        "Notation:",
        "- Name (5) => game_count=1, cumulative_total=5",
        "- Name 2 (5) => game_count=2, cumulative_total=5",
        "- Name => game_count=1, cumulative_total unknown",
        "",
        "No ambiguous short-name event is guessed.",
        "Rows with no canonical game-log player remain unresolved; v3 does not synthesize fielding-only player rows.",
    ]
    return "\n".join(lines) + "\n"

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enrich 2025 canonical game logs from BSM raw HTML with v3 final-total constraints."
    )
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--game-logs", type=Path)
    parser.add_argument("--season-json", type=Path)
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
    season_json_path = args.season_json or (
        project_root / "data" / "seasons" / "2025.json"
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
    if not season_json_path.exists():
        raise FileNotFoundError(f"Canonical season JSON not found: {season_json_path}")

    payload = read_json(game_logs_path)
    season_payload = read_json(season_json_path)
    enriched, report = enrich_dataset(payload, raw_dir, season_payload)

    report_json = report_dir / "event_enrichment_report_v3_1.json"
    report_txt = report_dir / "event_enrichment_report_v3_1.txt"
    unresolved_json = report_dir / "event_enrichment_unresolved_v3_1.json"
    resolved_v2_json = report_dir / "event_enrichment_resolved_v2.json"
    resolved_v3_json = report_dir / "event_enrichment_resolved_v3_1.json"
    ignored_v31_json = report_dir / "event_enrichment_ignored_v3_1.json"

    write_json(report_json, report)
    write_json(unresolved_json, report["unresolved"])
    write_json(ignored_v31_json, report.get("ignored_v3_1") or [])
    write_json(resolved_v2_json, report.get("resolved_v2") or [])
    write_json(resolved_v3_json, report.get("resolved_v3") or [])
    report_txt.parent.mkdir(parents=True, exist_ok=True)
    report_txt.write_text(render_report(report), encoding="utf-8")

    print(render_report(report), end="")
    print(f"Report JSON: {report_json}")
    print(f"Report text: {report_txt}")
    print(f"Unresolved JSON: {unresolved_json}")
    print(f"Resolved v2 JSON: {resolved_v2_json}")
    print(f"Resolved v3.1 JSON: {resolved_v3_json}")
    print(f"Ignored v3.1 JSON: {ignored_v31_json}")

    if args.write:
        if report["summary"]["validation_errors"]:
            raise RuntimeError(
                "Refusing --write because validation errors remain. "
                "Fix or review the report first."
            )
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
