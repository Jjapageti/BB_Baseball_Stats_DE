#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
2025 Boxscore player-name matcher.

목적
----
BSM Boxscore의 축약 이름:
    Krause M. ss
    Del Muro Puente L. (W, 1-0)

을 시즌 JSON의 정식 Person:
    Maximilian Krause      -> person_id 69791
    Luis Orlando Del Muro Puente -> person_id 65411

와 안전하게 연결한다.

중요
----
- 이름만으로 억지 매칭하지 않는다.
- 같은 리그(group_id) + 같은 팀 + 성 + 이름 첫 글자가 유일할 때만 auto.
- 현재 season JSON 자체에 없는 리그는 canonical_scope_missing으로 분리한다.
- 애매한 후보는 ambiguous/review로 남긴다.

기본 입력 자동 탐색:
- data/seasons/2025.json
- tests/bsm_season_data/2025_discovery_v2/boxscores_parsed/
- tests/bsm_season_data/2025_discovery_v2/candidate_matches.json

기본 출력:
- tests/bsm_season_data/2025_discovery_v2/player_match_report_v8.json
- tests/bsm_season_data/2025_discovery_v2/player_match_report_v8.txt
- tests/bsm_season_data/2025_discovery_v2/player_match_unresolved_v8.json
- tests/bsm_season_data/2025_discovery_v2/player_match_unresolved_v8.txt
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


POSITION_TOKEN = r"(?:p|c|1b|2b|3b|ss|lf|cf|rf|dh|ph|pr|of|if|dp|flex)"
POSITION_RE = re.compile(
    rf"\s+{POSITION_TOKEN}(?:[/,\-]{POSITION_TOKEN})*\s*$",
    re.IGNORECASE,
)
DECISION_RE = re.compile(r"\s*\([^)]*\)\s*$")
PITCHING_DECISION_RE = re.compile(r"\(\s*([WLS])\s*,\s*([^\)]+?)\s*\)\s*$", re.IGNORECASE)


SAME_PERSON_OVERRIDES = []

SEASON_TOTAL_SPLIT_IDENTITIES = [
    {
        "clean_name_key": "bonge j.",
        "candidate_person_ids": frozenset({71909, 73795}),
    },
    {
        "clean_name_key": "honicke l.",
        "candidate_person_ids": frozenset({63549, 71804}),
    },
    {
        "clean_name_key": "el-mahmoud m.",
        "candidate_person_ids": frozenset({80554, 80555}),
    },
]

INITIAL_RE = re.compile(r"^([A-Za-zÀ-ÖØ-öø-ÿ])\.$")


def compact_spaces(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", compact_spaces(value)).casefold()


def accentfold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", normalize(value))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def canonical_full_name(person: dict[str, Any]) -> str:
    return compact_spaces(" ".join(
        str(person.get(key) or "")
        for key in ("name_prefix", "first_name", "last_name", "name_suffix")
    ))


def parse_position_sequence(raw_name: str) -> list[str]:
    """Return the ordered BSM position sequence at the end of a batting row."""
    without_decision = DECISION_RE.sub("", compact_spaces(raw_name)).strip()
    match = POSITION_RE.search(without_decision)
    if not match:
        return []

    token_text = match.group(0).strip().casefold()
    return [
        token
        for token in re.split(r"[/,\-]", token_text)
        if token
    ]


def parse_pitching_decision(raw_name: str) -> dict[str, str | None]:
    """Separate pitching decision metadata such as '(W, 2-0)' from the name."""
    match = PITCHING_DECISION_RE.search(compact_spaces(raw_name))
    if not match:
        return {"decision": None, "cumulative_record": None}

    return {
        "decision": match.group(1).upper(),
        "cumulative_record": compact_spaces(match.group(2)),
    }


def parse_boxscore_player_name(raw_name: str) -> dict[str, str | None]:
    clean = compact_spaces(raw_name)
    clean = DECISION_RE.sub("", clean).strip()
    clean = POSITION_RE.sub("", clean).strip()

    tokens = clean.split()
    initial: str | None = None
    surname = clean

    if tokens:
        m = INITIAL_RE.match(tokens[-1])
        if m:
            initial = m.group(1)
            surname = " ".join(tokens[:-1]).strip()

    return {
        "clean_name": clean,
        "surname": surname,
        "initial": initial,
    }


def _team_aliases(entry: dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for value in (entry.get("name"), entry.get("acronym")):
        if value:
            aliases.add(accentfold(str(value)))

    club = entry.get("club") or {}
    for value in (
        club.get("name"),
        club.get("acronym"),
        club.get("short_name"),
    ):
        if value:
            aliases.add(accentfold(str(value)))

    for club_item in entry.get("clubs") or []:
        if not isinstance(club_item, dict):
            continue
        for value in (
            club_item.get("name"),
            club_item.get("acronym"),
            club_item.get("short_name"),
        ):
            if value:
                aliases.add(accentfold(str(value)))

    return aliases


def _club_ids(entry: dict[str, Any]) -> set[int]:
    ids: set[int] = set()

    club = entry.get("club") or {}
    club_id = club.get("id")
    if isinstance(club_id, int):
        ids.add(club_id)

    for club_item in entry.get("clubs") or []:
        if not isinstance(club_item, dict):
            continue
        club_id = club_item.get("id")
        if isinstance(club_id, int):
            ids.add(club_id)

    return ids


def _club_metadata_mentions_berlin(club: dict[str, Any]) -> bool:
    for key in ("name", "short_name"):
        value = club.get(key)
        if value and "berlin" in accentfold(str(value)):
            return True
    return False


def berlin_club_ids_from_candidates(
    candidate_matches: list[dict[str, Any]],
) -> set[int]:
    """Return BSVBB club IDs whose metadata explicitly identifies Berlin."""
    result: set[int] = set()
    for match in candidate_matches:
        if not isinstance(match, dict):
            continue
        for club in match.get("bsvbb_clubs_in_match") or []:
            if not isinstance(club, dict):
                continue
            club_id = club.get("id")
            if isinstance(club_id, int) and _club_metadata_mentions_berlin(club):
                result.add(club_id)
    return result


def is_berlin_boxscore_team(
    team_name: str,
    index: dict[str, Any],
    berlin_club_ids: set[int],
    league_ids: set[int] | None = None,
) -> bool:
    if not berlin_club_ids:
        return False

    team_key = accentfold(team_name)
    league_ids = league_ids or set()

    if league_ids:
        group_map = index.get("team_alias_group_to_club_ids", {})
        club_ids: set[int] = set()
        had_group_mapping = False
        for group_id in league_ids:
            key = (team_key, group_id)
            if key in group_map:
                had_group_mapping = True
                club_ids.update(group_map[key])
        if had_group_mapping:
            return bool(club_ids.intersection(berlin_club_ids))

    club_ids = set(index.get("team_alias_to_club_ids", {}).get(team_key, set()))
    return bool(club_ids.intersection(berlin_club_ids))


def berlin_boxscore_club_id(
    team_name: str,
    index: dict[str, Any],
    berlin_club_ids: set[int],
    league_ids: set[int] | None = None,
) -> int | None:
    """Resolve a Boxscore team alias to one Berlin club id when unique."""
    if not berlin_club_ids:
        return None

    team_key = accentfold(team_name)
    league_ids = league_ids or set()
    candidates: set[int] = set()

    if league_ids:
        group_map = index.get("team_alias_group_to_club_ids", {})
        had_group_mapping = False
        for group_id in league_ids:
            key = (team_key, group_id)
            if key in group_map:
                had_group_mapping = True
                candidates.update(group_map[key])
        if had_group_mapping:
            candidates.intersection_update(berlin_club_ids)
            return next(iter(candidates)) if len(candidates) == 1 else None

    candidates = set(index.get("team_alias_to_club_ids", {}).get(team_key, set()))
    candidates.intersection_update(berlin_club_ids)
    return next(iter(candidates)) if len(candidates) == 1 else None


def build_canonical_index(season_data: dict[str, Any]) -> dict[str, Any]:
    people: dict[int, dict[str, Any]] = {}
    covered_group_ids: set[int] = set()

    # Aggregate batting/pitching roles into the same team/group context.
    context_maps: dict[int, dict[tuple[Any, ...], dict[str, Any]]] = defaultdict(dict)
    team_alias_to_club_ids: dict[str, set[int]] = defaultdict(set)
    team_alias_group_to_club_ids: dict[tuple[str, int], set[int]] = defaultdict(set)

    for league in season_data.get("leagues") or []:
        league_key = league.get("key")
        for role in ("batting", "pitching"):
            for stat in league.get(role) or []:
                if not isinstance(stat, dict):
                    continue

                person = stat.get("person") or {}
                person_id = person.get("id")
                if not isinstance(person_id, int):
                    continue

                first_name = compact_spaces(str(person.get("first_name") or ""))
                last_name = compact_spaces(str(person.get("last_name") or ""))
                full_name = canonical_full_name(person)
                entry = stat.get("league_entry") or {}

                group_ids = {
                    gid for gid in (entry.get("group_ids") or [])
                    if isinstance(gid, int)
                }
                covered_group_ids.update(group_ids)
                team_aliases = sorted(_team_aliases(entry))
                entry_club_ids = _club_ids(entry)
                for alias in team_aliases:
                    team_alias_to_club_ids[alias].update(entry_club_ids)
                    for group_id in group_ids:
                        team_alias_group_to_club_ids[(alias, group_id)].update(entry_club_ids)

                people[person_id] = {
                    "person_id": person_id,
                    "canonical_name": full_name,
                    "first_name": first_name,
                    "last_name": last_name,
                    "surname_key": accentfold(last_name),
                    "initial_key": accentfold(first_name)[:1],
                }

                context_key = (
                    league_key,
                    entry.get("id"),
                    tuple(sorted(group_ids)),
                    tuple(team_aliases),
                )
                existing = context_maps[person_id].get(context_key)
                if existing is None:
                    existing = {
                        "league_key": league_key,
                        "league_entry_id": entry.get("id"),
                        "entry_name": entry.get("name"),
                        "entry_acronym": entry.get("acronym"),
                        "group_ids": sorted(group_ids),
                        "team_aliases": team_aliases,
                        "club_ids": sorted(entry_club_ids),
                        "roles": [],
                    }
                    context_maps[person_id][context_key] = existing

                if role not in existing["roles"]:
                    existing["roles"].append(role)
                    existing["roles"].sort()

                existing.setdefault("values_by_role", {})[role] = dict(stat.get("values") or {})

    contexts_by_person = {
        person_id: list(context_map.values())
        for person_id, context_map in context_maps.items()
    }

    return {
        "people": people,
        "contexts_by_person": contexts_by_person,
        "covered_group_ids": covered_group_ids,
        "team_alias_to_club_ids": dict(team_alias_to_club_ids),
        "team_alias_group_to_club_ids": dict(team_alias_group_to_club_ids),
    }


def _person_ids_matching_name(
    parsed: dict[str, str | None],
    index: dict[str, Any],
) -> tuple[list[int], str]:
    raw_surname = str(parsed.get("surname") or "")
    surname_key = accentfold(raw_surname)
    initial = parsed.get("initial")
    initial_key = accentfold(str(initial or ""))[:1]

    is_prefix = "..." in raw_surname
    prefix_key = accentfold(raw_surname.split("...", 1)[0]).rstrip(" .,-_/")

    result: list[int] = []
    for person_id, person in index["people"].items():
        person_surname = person["surname_key"]

        if is_prefix:
            if not prefix_key or not person_surname.startswith(prefix_key):
                continue
        elif person_surname != surname_key:
            continue

        if initial_key and person["initial_key"] != initial_key:
            continue
        result.append(person_id)

    method_name = "surname-prefix+initial" if is_prefix else "surname+initial"
    return sorted(set(result)), method_name


def _person_context_matches(
    person_id: int,
    *,
    league_ids: set[int],
    team_key: str,
    role: str | None,
    index: dict[str, Any],
    require_group: bool,
    require_team: bool,
    require_role: bool,
) -> bool:
    for context in index["contexts_by_person"].get(person_id, []):
        if require_group and not league_ids.intersection(context.get("group_ids") or []):
            continue
        if require_team and (
            not team_key or team_key not in set(context.get("team_aliases") or [])
        ):
            continue
        if require_role and (
            not role or role not in set(context.get("roles") or [])
        ):
            continue
        return True
    return False


def _person_has_group(
    person_id: int,
    league_ids: set[int],
    index: dict[str, Any],
) -> bool:
    return _person_context_matches(
        person_id,
        league_ids=league_ids,
        team_key="",
        role=None,
        index=index,
        require_group=True,
        require_team=False,
        require_role=False,
    )


def _person_has_team(
    person_id: int,
    team_key: str,
    index: dict[str, Any],
) -> bool:
    return _person_context_matches(
        person_id,
        league_ids=set(),
        team_key=team_key,
        role=None,
        index=index,
        require_group=False,
        require_team=True,
        require_role=False,
    )


def _person_has_group_and_team(
    person_id: int,
    league_ids: set[int],
    team_key: str,
    index: dict[str, Any],
) -> bool:
    return _person_context_matches(
        person_id,
        league_ids=league_ids,
        team_key=team_key,
        role=None,
        index=index,
        require_group=True,
        require_team=True,
        require_role=False,
    )


def _person_has_group_team_role(
    person_id: int,
    league_ids: set[int],
    team_key: str,
    role: str,
    index: dict[str, Any],
) -> bool:
    return _person_context_matches(
        person_id,
        league_ids=league_ids,
        team_key=team_key,
        role=role,
        index=index,
        require_group=True,
        require_team=True,
        require_role=True,
    )


def _person_has_team_role(
    person_id: int,
    team_key: str,
    role: str,
    index: dict[str, Any],
) -> bool:
    return _person_context_matches(
        person_id,
        league_ids=set(),
        team_key=team_key,
        role=role,
        index=index,
        require_group=False,
        require_team=True,
        require_role=True,
    )


def _person_has_group_role(
    person_id: int,
    league_ids: set[int],
    role: str,
    index: dict[str, Any],
) -> bool:
    return _person_context_matches(
        person_id,
        league_ids=league_ids,
        team_key="",
        role=role,
        index=index,
        require_group=True,
        require_team=False,
        require_role=True,
    )


def _auto_result(
    person_id: int,
    method: str,
    parsed: dict[str, str | None],
    index: dict[str, Any],
) -> dict[str, Any]:
    person = index["people"][person_id]
    return {
        "status": "auto",
        "method": method,
        "person_id": person_id,
        "canonical_name": person["canonical_name"],
        "candidate_person_ids": [person_id],
        "parsed_name": parsed,
    }


def match_player(
    *,
    raw_name: str,
    boxscore_team: str,
    league_ids: list[int] | set[int],
    index: dict[str, Any],
    role: str | None = None,
) -> dict[str, Any]:
    parsed = parse_boxscore_player_name(raw_name)
    league_id_set = {x for x in league_ids if isinstance(x, int)}

    if league_id_set and not league_id_set.intersection(index["covered_group_ids"]):
        return {
            "status": "canonical_scope_missing",
            "method": None,
            "person_id": None,
            "canonical_name": None,
            "candidate_person_ids": [],
            "parsed_name": parsed,
        }

    name_candidates, name_method = _person_ids_matching_name(parsed, index)
    if not name_candidates:
        return {
            "status": "unmatched",
            "method": None,
            "person_id": None,
            "canonical_name": None,
            "candidate_person_ids": [],
            "parsed_name": parsed,
        }

    team_key = accentfold(boxscore_team)

    strong = sorted({
        pid for pid in name_candidates
        if _person_has_group_and_team(pid, league_id_set, team_key, index)
    })
    if len(strong) == 1:
        return _auto_result(
            strong[0],
            f"group+team+{name_method}",
            parsed,
            index,
        )
    if len(strong) > 1:
        if role:
            role_strong = sorted({
                pid for pid in strong
                if _person_has_group_team_role(
                    pid, league_id_set, team_key, role, index
                )
            })
            if len(role_strong) == 1:
                return _auto_result(
                    role_strong[0],
                    f"group+team+role+{name_method}",
                    parsed,
                    index,
                )
            if len(role_strong) > 1:
                strong = role_strong
                method = f"group+team+role+{name_method}"
            else:
                method = f"group+team+{name_method}"
        else:
            method = f"group+team+{name_method}"

        return {
            "status": "ambiguous",
            "method": method,
            "person_id": None,
            "canonical_name": None,
            "candidate_person_ids": strong,
            "parsed_name": parsed,
        }

    team_candidates = sorted({
        pid for pid in name_candidates
        if _person_has_team(pid, team_key, index)
    })
    if len(team_candidates) == 1:
        return _auto_result(
            team_candidates[0],
            f"team+{name_method}",
            parsed,
            index,
        )
    if len(team_candidates) > 1:
        if role:
            role_team = sorted({
                pid for pid in team_candidates
                if _person_has_team_role(pid, team_key, role, index)
            })
            if len(role_team) == 1:
                return _auto_result(
                    role_team[0],
                    f"team+role+{name_method}",
                    parsed,
                    index,
                )
            if len(role_team) > 1:
                team_candidates = role_team
                method = f"team+role+{name_method}"
            else:
                method = f"team+{name_method}"
        else:
            method = f"team+{name_method}"

        return {
            "status": "ambiguous",
            "method": method,
            "person_id": None,
            "canonical_name": None,
            "candidate_person_ids": team_candidates,
            "parsed_name": parsed,
        }

    group_candidates = sorted({
        pid for pid in name_candidates
        if _person_has_group(pid, league_id_set, index)
    })
    if len(group_candidates) == 1:
        pid = group_candidates[0]
        return {
            "status": "review",
            "method": f"group+{name_method}",
            "person_id": pid,
            "canonical_name": index["people"][pid]["canonical_name"],
            "candidate_person_ids": [pid],
            "parsed_name": parsed,
        }
    if len(group_candidates) > 1:
        method = f"group+{name_method}"
        if role:
            role_group = sorted({
                pid for pid in group_candidates
                if _person_has_group_role(pid, league_id_set, role, index)
            })
            if len(role_group) == 1:
                pid = role_group[0]
                return {
                    "status": "review",
                    "method": f"group+role+{name_method}",
                    "person_id": pid,
                    "canonical_name": index["people"][pid]["canonical_name"],
                    "candidate_person_ids": [pid],
                    "parsed_name": parsed,
                }
            if len(role_group) > 1:
                group_candidates = role_group
                method = f"group+role+{name_method}"

        return {
            "status": "ambiguous",
            "method": method,
            "person_id": None,
            "canonical_name": None,
            "candidate_person_ids": group_candidates,
            "parsed_name": parsed,
        }

    if len(name_candidates) == 1:
        pid = name_candidates[0]
        return {
            "status": "review",
            "method": name_method,
            "person_id": pid,
            "canonical_name": index["people"][pid]["canonical_name"],
            "candidate_person_ids": [pid],
            "parsed_name": parsed,
        }

    return {
        "status": "ambiguous",
        "method": name_method,
        "person_id": None,
        "canonical_name": None,
        "candidate_person_ids": name_candidates,
        "parsed_name": parsed,
    }


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def find_file_from_roots(relative_paths: list[Path]) -> Path | None:
    script_dir = Path(__file__).resolve().parent
    roots: list[Path] = []
    for root in [Path.cwd().resolve(), script_dir, *script_dir.parents]:
        if root not in roots:
            roots.append(root)

    for root in roots:
        for rel in relative_paths:
            candidate = root / rel
            if candidate.exists():
                return candidate
    return None


def discover_defaults() -> tuple[Path | None, Path | None, Path | None]:
    season_file = find_file_from_roots([
        Path("data/seasons/2025.json"),
        Path("data/2025.json"),
        Path("2025.json"),
    ])
    candidate_file = find_file_from_roots([
        Path("tests/bsm_season_data/2025_discovery_v2/candidate_matches.json"),
        Path("bsm_season_data/2025_discovery_v2/candidate_matches.json"),
    ])
    boxscore_dir = find_file_from_roots([
        Path("tests/bsm_season_data/2025_discovery_v2/boxscores_parsed"),
        Path("bsm_season_data/2025_discovery_v2/boxscores_parsed"),
    ])
    return season_file, candidate_file, boxscore_dir


def candidate_match_map(candidate_matches: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {
        row["id"]: row
        for row in candidate_matches
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }


def boxscore_occurrences(
    boxscore: dict[str, Any],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for role in ("batting", "pitching"):
        for team_table in boxscore.get(role) or []:
            team = str(team_table.get("team") or "")
            for player_row in team_table.get("players") or []:
                if not isinstance(player_row, dict):
                    continue
                raw_name = str(player_row.get("player") or "").strip()
                if not raw_name:
                    continue
                result.append({
                    "role": role,
                    "team": team,
                    "raw_name": raw_name,
                    "stats": dict(player_row),
                })
    return result


def build_match_report(
    *,
    season_data: dict[str, Any],
    candidate_matches: list[dict[str, Any]],
    boxscore_files: list[Path],
) -> dict[str, Any]:
    index = build_canonical_index(season_data)
    candidate_by_id = candidate_match_map(candidate_matches)
    berlin_club_ids = berlin_club_ids_from_candidates(candidate_matches)

    rows: list[dict[str, Any]] = []
    status_counter: Counter[str] = Counter()
    matches_scope_missing: set[int] = set()
    matches_seen: set[int] = set()
    matches_with_berlin_player_rows: set[int] = set()
    boxscore_player_occurrences_total = 0
    non_berlin_skipped = 0

    for path in sorted(boxscore_files, key=lambda p: p.name):
        boxscore = load_json(path)
        match_id = boxscore.get("match_id")
        if not isinstance(match_id, int):
            try:
                match_id = int(path.stem)
            except ValueError:
                continue

        matches_seen.add(match_id)
        meta = candidate_by_id.get(match_id, {})
        league_refs = meta.get("candidate_leagues") or []
        league_ids = [
            ref.get("league_id")
            for ref in league_refs
            if isinstance(ref, dict) and isinstance(ref.get("league_id"), int)
        ]

        if league_ids and not set(league_ids).intersection(index["covered_group_ids"]):
            matches_scope_missing.add(match_id)

        for occurrence in boxscore_occurrences(boxscore):
            boxscore_player_occurrences_total += 1
            berlin_club_id = berlin_boxscore_club_id(
                occurrence["team"],
                index,
                berlin_club_ids,
                set(league_ids),
            )
            if berlin_club_id is None:
                non_berlin_skipped += 1
                continue

            matches_with_berlin_player_rows.add(match_id)
            matched = match_player(
                raw_name=occurrence["raw_name"],
                boxscore_team=occurrence["team"],
                league_ids=league_ids,
                role=occurrence["role"],
                index=index,
            )
            status_counter[matched["status"]] += 1

            rows.append({
                "match_id": match_id,
                "match_number": meta.get("match_id"),
                "time": meta.get("time"),
                "league_ids": league_ids,
                "league_acronyms": [
                    ref.get("league_acronym")
                    for ref in league_refs
                    if isinstance(ref, dict)
                ],
                "home_team": meta.get("home_team"),
                "away_team": meta.get("away_team"),
                "role": occurrence["role"],
                "boxscore_team": occurrence["team"],
                "berlin_club_id": berlin_club_id,
                "raw_name": occurrence["raw_name"],
                "position_sequence": (
                    parse_position_sequence(occurrence["raw_name"])
                    if occurrence["role"] == "batting"
                    else []
                ),
                **parse_pitching_decision(occurrence["raw_name"]),
                "stats": occurrence["stats"],
                **matched,
            })

    report = {
        "season": season_data.get("season"),
        "canonical": {
            "people": len(index["people"]),
            "covered_group_ids": sorted(index["covered_group_ids"]),
            "berlin_club_ids": sorted(berlin_club_ids),
        },
        "summary": {},
        "rows": rows,
    }

    identity_override_resolved = apply_same_person_overrides(report)
    cumulative_resolved = 0
    season_total_resolved = 0
    role_link_resolved = 0
    pitching_record_resolved = 0

    # Evidence passes can seed one another. v8 has no same-person merges:
    # every configured short-name collision must resolve to a canonical ID.
    for _ in range(8):
        cumulative_now = resolve_ambiguous_by_cumulative_totals(report, index)
        season_total_now = resolve_configured_season_total_splits(report, index)
        role_now = resolve_ambiguous_by_role_linkage(report, index)
        pitching_record_now = resolve_configured_pitching_record_chains(
            report,
            index,
        )
        cumulative_resolved += cumulative_now
        season_total_resolved += season_total_now
        role_link_resolved += role_now
        pitching_record_resolved += pitching_record_now
        if (
            cumulative_now == 0
            and season_total_now == 0
            and role_now == 0
            and pitching_record_now == 0
        ):
            break

    final_counter = Counter(row.get("status") for row in rows)
    total = len(rows)
    auto = final_counter.get("auto", 0)
    merged_identity = final_counter.get("merged_identity", 0)
    report["summary"] = {
        "boxscore_files": len(boxscore_files),
        "matches_seen": len(matches_seen),
        "matches_with_berlin_player_rows": len(matches_with_berlin_player_rows),
        "matches_canonical_scope_missing": len(matches_scope_missing),
        "boxscore_player_occurrences_total": boxscore_player_occurrences_total,
        "player_occurrences_non_berlin_skipped": non_berlin_skipped,
        "player_occurrences": total,
        "auto": auto,
        "merged_identity": merged_identity,
        "boxscore_identity": final_counter.get("boxscore_identity", 0),
        "review": final_counter.get("review", 0),
        "ambiguous": final_counter.get("ambiguous", 0),
        "unmatched": final_counter.get("unmatched", 0),
        "canonical_scope_missing": final_counter.get("canonical_scope_missing", 0),
        "resolved_by_identity_override": identity_override_resolved,
        "resolved_by_cumulative_totals": cumulative_resolved,
        "resolved_by_season_total_constraints": season_total_resolved,
        "resolved_by_role_linkage": role_link_resolved,
        "resolved_by_pitching_record_chain": pitching_record_resolved,
        "auto_rate_percent": round((auto / total * 100) if total else 0.0, 2),
        "resolved_rate_percent": round(
            (auto / total * 100) if total else 0.0,
            2,
        ),
    }
    return report


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")


def _batting_metric_from_state(at_bats: int, hits: int) -> str:
    if at_bats <= 0:
        return ".000"
    return f"{hits / at_bats:.3f}".lstrip("0")


def _normalize_avg(value: Any) -> str:
    try:
        return f"{float(value):.3f}".lstrip("0")
    except (TypeError, ValueError):
        return str(value or "")


def _innings_to_outs(value: Any) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if "." not in raw:
        try:
            return int(raw) * 3
        except ValueError:
            return None

    whole, frac = raw.split(".", 1)
    try:
        innings = int(whole or "0")
        partial = int(frac[:1] or "0")
    except ValueError:
        return None

    if partial not in (0, 1, 2):
        return None
    return innings * 3 + partial


def _pitching_metric_from_state(outs: int, earned_runs: int) -> str:
    if outs <= 0:
        return "0.00"
    return f"{earned_runs * 27 / outs:.2f}"


def _normalize_era(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value or "")


def _matching_role_contexts(
    *,
    person_id: int,
    role: str,
    league_ids: set[int],
    team_key: str,
    index: dict[str, Any],
) -> list[dict[str, Any]]:
    contexts = []
    for context in index["contexts_by_person"].get(person_id, []):
        if role not in set(context.get("roles") or []):
            continue
        if league_ids and not league_ids.intersection(context.get("group_ids") or []):
            continue
        if team_key and team_key not in set(context.get("team_aliases") or []):
            continue
        values = (context.get("values_by_role") or {}).get(role) or {}
        if values:
            contexts.append(context)
    return contexts


def _known_auto_role_totals(
    *,
    report: dict[str, Any],
    person_id: int,
    context: dict[str, Any],
    role: str,
) -> tuple[int, int]:
    context_groups = set(context.get("group_ids") or [])
    context_teams = set(context.get("team_aliases") or [])
    first_total = 0
    second_total = 0

    for row in report.get("rows") or []:
        if row.get("status") != "auto":
            continue
        if row.get("person_id") != person_id:
            continue
        if row.get("role") != role:
            continue

        row_groups = set(row.get("league_ids") or [])
        if context_groups and not context_groups.intersection(row_groups):
            continue

        if accentfold(str(row.get("boxscore_team") or "")) not in context_teams:
            continue

        stats = row.get("stats") or {}
        try:
            if role == "batting":
                first_total += int(stats.get("AB") or 0)
                second_total += int(stats.get("H") or 0)
            elif role == "pitching":
                outs = _innings_to_outs(stats.get("IP"))
                if outs is None:
                    continue
                first_total += outs
                second_total += int(stats.get("ER") or 0)
        except (TypeError, ValueError):
            continue

    return first_total, second_total


def _solve_reverse_batting_group(
    *,
    rows: list[dict[str, Any]],
    candidate_ids: list[int],
    index: dict[str, Any],
    report: dict[str, Any],
) -> dict[int, int] | None:
    if not rows or len(candidate_ids) < 2:
        return None

    league_ids = {
        group_id
        for row in rows
        for group_id in (row.get("league_ids") or [])
        if isinstance(group_id, int)
    }
    team_key = accentfold(str(rows[0].get("boxscore_team") or ""))

    contexts: dict[int, dict[str, Any]] = {}
    states: dict[int, tuple[int, int]] = {}

    for person_id in candidate_ids:
        matching = _matching_role_contexts(
            person_id=person_id,
            role="batting",
            league_ids=league_ids,
            team_key=team_key,
            index=index,
        )
        if len(matching) != 1:
            return None

        context = matching[0]
        values = (context.get("values_by_role") or {}).get("batting") or {}
        try:
            target_ab = int(values.get("at_bats"))
            target_h = int(values.get("hits"))
        except (TypeError, ValueError):
            return None

        known_ab, known_h = _known_auto_role_totals(
            report=report,
            person_id=person_id,
            context=context,
            role="batting",
        )
        target_ab -= known_ab
        target_h -= known_h
        if target_ab < 0 or target_h < 0:
            return None

        contexts[person_id] = context
        states[person_id] = (target_ab, target_h)

    match_groups: dict[tuple[datetime, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        try:
            key = (_parse_time(str(row.get("time"))), int(row.get("match_id")))
        except (TypeError, ValueError):
            return None
        match_groups[key].append(row)

    ordered_groups = [
        match_groups[key]
        for key in sorted(match_groups.keys(), reverse=True)
    ]

    solutions: list[dict[int, int]] = []

    def recurse(
        group_index: int,
        current_states: dict[int, tuple[int, int]],
        assignment: dict[int, int],
    ) -> None:
        if len(solutions) >= 2:
            return

        if group_index >= len(ordered_groups):
            if all(state == (0, 0) for state in current_states.values()):
                solutions.append(dict(assignment))
            return

        group_rows = ordered_groups[group_index]
        if len(group_rows) > len(candidate_ids):
            return

        import itertools

        for chosen_ids in itertools.permutations(candidate_ids, len(group_rows)):
            next_states = dict(current_states)
            next_assignment = dict(assignment)
            valid = True

            for row, person_id in zip(group_rows, chosen_ids):
                current_ab, current_h = next_states[person_id]
                displayed_avg = _normalize_avg((row.get("stats") or {}).get("AVG"))
                if displayed_avg != _batting_metric_from_state(current_ab, current_h):
                    valid = False
                    break

                try:
                    game_ab = int((row.get("stats") or {}).get("AB") or 0)
                    game_h = int((row.get("stats") or {}).get("H") or 0)
                except (TypeError, ValueError):
                    valid = False
                    break

                previous = (current_ab - game_ab, current_h - game_h)
                if previous[0] < 0 or previous[1] < 0:
                    valid = False
                    break

                next_states[person_id] = previous
                next_assignment[id(row)] = person_id

            if valid:
                recurse(group_index + 1, next_states, next_assignment)

    recurse(0, states, {})

    if len(solutions) != 1:
        return None
    return solutions[0]


def _solve_reverse_pitching_group(
    *,
    rows: list[dict[str, Any]],
    candidate_ids: list[int],
    index: dict[str, Any],
    report: dict[str, Any],
) -> dict[int, int] | None:
    if not rows or len(candidate_ids) < 2:
        return None

    league_ids = {
        group_id
        for row in rows
        for group_id in (row.get("league_ids") or [])
        if isinstance(group_id, int)
    }
    team_key = accentfold(str(rows[0].get("boxscore_team") or ""))

    states: dict[int, tuple[int, int]] = {}

    for person_id in candidate_ids:
        matching = _matching_role_contexts(
            person_id=person_id,
            role="pitching",
            league_ids=league_ids,
            team_key=team_key,
            index=index,
        )
        if len(matching) != 1:
            return None

        context = matching[0]
        values = (context.get("values_by_role") or {}).get("pitching") or {}
        target_outs = _innings_to_outs(values.get("innings_pitched"))
        try:
            target_er = int(values.get("earned_runs"))
        except (TypeError, ValueError):
            return None
        if target_outs is None:
            return None

        known_outs, known_er = _known_auto_role_totals(
            report=report,
            person_id=person_id,
            context=context,
            role="pitching",
        )
        target_outs -= known_outs
        target_er -= known_er
        if target_outs < 0 or target_er < 0:
            return None

        states[person_id] = (target_outs, target_er)

    match_groups: dict[tuple[datetime, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        try:
            key = (_parse_time(str(row.get("time"))), int(row.get("match_id")))
        except (TypeError, ValueError):
            return None
        match_groups[key].append(row)

    ordered_groups = [
        match_groups[key]
        for key in sorted(match_groups.keys(), reverse=True)
    ]

    solutions: list[dict[int, int]] = []

    def recurse(
        group_index: int,
        current_states: dict[int, tuple[int, int]],
        assignment: dict[int, int],
    ) -> None:
        if len(solutions) >= 2:
            return

        if group_index >= len(ordered_groups):
            if all(state == (0, 0) for state in current_states.values()):
                solutions.append(dict(assignment))
            return

        group_rows = ordered_groups[group_index]
        if len(group_rows) > len(candidate_ids):
            return

        import itertools

        for chosen_ids in itertools.permutations(candidate_ids, len(group_rows)):
            next_states = dict(current_states)
            next_assignment = dict(assignment)
            valid = True

            for row, person_id in zip(group_rows, chosen_ids):
                current_outs, current_er = next_states[person_id]
                displayed_era = _normalize_era((row.get("stats") or {}).get("ERA"))
                if displayed_era != _pitching_metric_from_state(current_outs, current_er):
                    valid = False
                    break

                game_outs = _innings_to_outs((row.get("stats") or {}).get("IP"))
                try:
                    game_er = int((row.get("stats") or {}).get("ER") or 0)
                except (TypeError, ValueError):
                    valid = False
                    break
                if game_outs is None:
                    valid = False
                    break

                previous = (current_outs - game_outs, current_er - game_er)
                if previous[0] < 0 or previous[1] < 0:
                    valid = False
                    break

                next_states[person_id] = previous
                next_assignment[id(row)] = person_id

            if valid:
                recurse(group_index + 1, next_states, next_assignment)

    recurse(0, states, {})

    if len(solutions) != 1:
        return None
    return solutions[0]


def apply_same_person_overrides(report: dict[str, Any]) -> int:
    """Apply explicit, audited same-person merges.

    v8 currently has no same-person overrides. Bongé J., Hönicke L. and
    El-Mahmoud M. are all treated as separate-person collisions and may only
    be resolved from statistical evidence.
    """
    season = report.get("season")
    changed = 0

    for row in report.get("rows") or []:
        clean_name = str((row.get("parsed_name") or {}).get("clean_name") or "")
        clean_name_key = accentfold(clean_name)
        club_id = row.get("berlin_club_id")

        row_candidates = {
            pid for pid in (row.get("candidate_person_ids") or [])
            if isinstance(pid, int)
        }
        if isinstance(row.get("person_id"), int):
            row_candidates.add(row["person_id"])

        for override in SAME_PERSON_OVERRIDES:
            if override["season"] != season:
                continue
            if override["club_id"] != club_id:
                continue
            if override["clean_name_key"] != clean_name_key:
                continue
            override_ids = set(override["candidate_person_ids"])
            if not row_candidates.intersection(override_ids):
                continue
            if not row_candidates.issubset(override_ids):
                continue

            before = (
                row.get("status"),
                row.get("person_id"),
                row.get("canonical_name"),
                tuple(row.get("candidate_person_ids") or []),
                row.get("player_key"),
            )
            row["status"] = "merged_identity"
            row["method"] = "explicit-same-person-override"
            row["person_id"] = None
            row["canonical_name"] = None
            row["candidate_person_ids"] = sorted(override_ids)
            row["player_key"] = override["player_key"]
            row["identity_source"] = "explicit_override"
            row["identity_assumption"] = "same_person_confirmed_by_project_review"

            after = (
                row.get("status"),
                row.get("person_id"),
                row.get("canonical_name"),
                tuple(row.get("candidate_person_ids") or []),
                row.get("player_key"),
            )
            if before != after:
                changed += 1
            break

    return changed


BATTING_TOTAL_FIELDS = (
    ("G", "games"),
    ("AB", "at_bats"),
    ("R", "runs"),
    ("RBI", "runs_batted_in"),
    ("H", "hits"),
    ("K", "strikeouts"),
    ("BB", "base_on_balls"),
)

PITCHING_TOTAL_FIELDS = (
    ("G", "games"),
    ("OUTS", "innings_pitched"),
    ("BF", "batters_faced"),
    ("AB", "at_bats"),
    ("H", "hits"),
    ("R", "runs"),
    ("ER", "earned_runs"),
    ("K", "strikeouts"),
    ("BB", "base_on_balls_allowed"),
    ("W", "wins"),
    ("L", "losses"),
    ("SV", "saves"),
)


def _canonical_total_vector(
    context: dict[str, Any],
    role: str,
) -> dict[str, int] | None:
    values = (context.get("values_by_role") or {}).get(role) or {}
    fields = BATTING_TOTAL_FIELDS if role == "batting" else PITCHING_TOTAL_FIELDS
    result: dict[str, int] = {}

    for output_key, canonical_key in fields:
        value = values.get(canonical_key)
        if output_key == "OUTS":
            outs = _innings_to_outs(value)
            if outs is None:
                return None
            result[output_key] = outs
            continue

        try:
            result[output_key] = int(value or 0)
        except (TypeError, ValueError):
            return None

    return result


def _row_total_vector(
    row: dict[str, Any],
    role: str,
) -> dict[str, int] | None:
    stats = row.get("stats") or {}

    if role == "batting":
        try:
            return {
                "G": 1,
                "AB": int(stats.get("AB") or 0),
                "R": int(stats.get("R") or 0),
                "RBI": int(stats.get("RBI") or 0),
                "H": int(stats.get("H") or 0),
                "K": int(stats.get("K") or 0),
                "BB": int(stats.get("BB") or 0),
            }
        except (TypeError, ValueError):
            return None

    outs = _innings_to_outs(stats.get("IP"))
    if outs is None:
        return None

    decision = str(row.get("decision") or "").upper()
    try:
        return {
            "G": 1,
            "OUTS": outs,
            "BF": int(stats.get("BF") or 0),
            "AB": int(stats.get("AB") or 0),
            "H": int(stats.get("H") or 0),
            "R": int(stats.get("R") or 0),
            "ER": int(stats.get("ER") or 0),
            "K": int(stats.get("K") or 0),
            "BB": int(stats.get("BB") or 0),
            "W": 1 if decision == "W" else 0,
            "L": 1 if decision == "L" else 0,
            "SV": 1 if decision == "S" else 0,
        }
    except (TypeError, ValueError):
        return None


def _known_auto_total_vector(
    *,
    report: dict[str, Any],
    person_id: int,
    context: dict[str, Any],
    role: str,
) -> dict[str, int] | None:
    target = _canonical_total_vector(context, role)
    if target is None:
        return None
    totals = {key: 0 for key in target}
    seen_games: set[int] = set()

    context_groups = set(context.get("group_ids") or [])
    context_teams = set(context.get("team_aliases") or [])

    for row in report.get("rows") or []:
        if row.get("status") != "auto":
            continue
        if row.get("person_id") != person_id or row.get("role") != role:
            continue

        row_groups = {
            gid for gid in (row.get("league_ids") or [])
            if isinstance(gid, int)
        }
        if context_groups and not context_groups.intersection(row_groups):
            continue
        if accentfold(str(row.get("boxscore_team") or "")) not in context_teams:
            continue

        vector = _row_total_vector(row, role)
        if vector is None:
            return None

        match_id = row.get("match_id")
        if isinstance(match_id, int) and match_id in seen_games:
            vector = dict(vector)
            vector["G"] = 0
        elif isinstance(match_id, int):
            seen_games.add(match_id)

        for key in totals:
            totals[key] += vector[key]

    return totals


def _subtract_vector(
    left: dict[str, int],
    right: dict[str, int],
) -> dict[str, int] | None:
    result = {}
    for key, value in left.items():
        remaining = value - right.get(key, 0)
        if remaining < 0:
            return None
        result[key] = remaining
    return result


def _vector_is_zero(vector: dict[str, int]) -> bool:
    return all(value == 0 for value in vector.values())


def _solve_season_total_group(
    *,
    rows: list[dict[str, Any]],
    candidate_ids: list[int],
    index: dict[str, Any],
    report: dict[str, Any],
    role: str,
) -> dict[int, int] | None:
    if not rows or len(candidate_ids) < 2:
        return None

    league_ids = {
        gid
        for row in rows
        for gid in (row.get("league_ids") or [])
        if isinstance(gid, int)
    }
    team_key = accentfold(str(rows[0].get("boxscore_team") or ""))

    states: dict[int, dict[str, int]] = {}
    for person_id in candidate_ids:
        contexts = _matching_role_contexts(
            person_id=person_id,
            role=role,
            league_ids=league_ids,
            team_key=team_key,
            index=index,
        )
        if len(contexts) != 1:
            return None

        target = _canonical_total_vector(contexts[0], role)
        known = _known_auto_total_vector(
            report=report,
            person_id=person_id,
            context=contexts[0],
            role=role,
        )
        if target is None or known is None:
            return None

        residual = _subtract_vector(target, known)
        if residual is None:
            return None
        states[person_id] = residual

    match_groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        match_id = row.get("match_id")
        if not isinstance(match_id, int):
            return None
        match_groups[match_id].append(row)

    # Largest/most distinctive games first improves pruning and keeps the
    # remaining configured groups tiny.
    ordered_groups = sorted(
        match_groups.values(),
        key=lambda group: (
            -len(group),
            -sum(sum((_row_total_vector(r, role) or {}).values()) for r in group),
            int(group[0].get("match_id") or 0),
        ),
    )

    import itertools

    solutions: list[dict[int, int]] = []

    def recurse(
        group_index: int,
        current_states: dict[int, dict[str, int]],
        assignment: dict[int, int],
    ) -> None:
        if len(solutions) >= 2:
            return
        if group_index >= len(ordered_groups):
            if all(_vector_is_zero(state) for state in current_states.values()):
                solutions.append(dict(assignment))
            return

        group_rows = ordered_groups[group_index]
        if len(group_rows) > len(candidate_ids):
            return

        for chosen_ids in itertools.permutations(candidate_ids, len(group_rows)):
            next_states = {
                pid: dict(vector)
                for pid, vector in current_states.items()
            }
            next_assignment = dict(assignment)
            valid = True

            for row, person_id in zip(group_rows, chosen_ids):
                vector = _row_total_vector(row, role)
                if vector is None:
                    valid = False
                    break
                residual = _subtract_vector(next_states[person_id], vector)
                if residual is None:
                    valid = False
                    break
                next_states[person_id] = residual
                next_assignment[id(row)] = person_id

            if valid:
                recurse(group_index + 1, next_states, next_assignment)

    recurse(0, states, {})

    if len(solutions) != 1:
        return None
    return solutions[0]


def resolve_configured_season_total_splits(
    report: dict[str, Any],
    index: dict[str, Any],
) -> int:
    """Split reviewed Bongé/Hönicke/El-Mahmoud abbreviation collisions.

    A row is auto-resolved only when the complete counting-stat season totals
    yield exactly one assignment. Otherwise it remains ambiguous.
    """
    configured = {
        (
            spec["clean_name_key"],
            frozenset(spec["candidate_person_ids"]),
        )
        for spec in SEASON_TOTAL_SPLIT_IDENTITIES
    }

    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in report.get("rows") or []:
        if row.get("status") != "ambiguous":
            continue
        role = row.get("role")
        if role not in {"batting", "pitching"}:
            continue

        clean_name_key = accentfold(
            str((row.get("parsed_name") or {}).get("clean_name") or "")
        )
        candidate_set = frozenset(
            pid for pid in (row.get("candidate_person_ids") or [])
            if isinstance(pid, int)
        )
        if (clean_name_key, candidate_set) not in configured:
            continue

        key = (
            role,
            clean_name_key,
            accentfold(str(row.get("boxscore_team") or "")),
            tuple(sorted(candidate_set)),
            tuple(sorted(
                gid for gid in (row.get("league_ids") or [])
                if isinstance(gid, int)
            )),
        )
        groups[key].append(row)

    changed = 0
    for key, rows in groups.items():
        role = key[0]
        candidate_ids = list(key[3])
        solution = _solve_season_total_group(
            rows=rows,
            candidate_ids=candidate_ids,
            index=index,
            report=report,
            role=role,
        )
        if not solution:
            continue

        method = f"season-total-constraint-{role}"
        for row in rows:
            person_id = solution.get(id(row))
            if person_id is None:
                continue
            if _set_auto_from_person(
                row,
                person_id,
                method=method,
                index=index,
            ):
                changed += 1

    return changed


def _parse_win_loss_record(value: Any) -> tuple[int, int] | None:
    match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", str(value or ""))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _pitching_record_chain_is_valid(rows: list[dict[str, Any]]) -> bool:
    """Validate differences between consecutive displayed W-L record anchors.

    This does not assume the first observed record starts at 0-0, so missing
    early-season games do not create false assignments.
    """
    ordered = sorted(
        rows,
        key=lambda row: (
            _parse_time(str(row.get("time"))),
            int(row.get("match_id") or 0),
        ),
    )
    anchors: list[tuple[int, tuple[int, int]]] = []
    for idx, row in enumerate(ordered):
        record = _parse_win_loss_record(row.get("cumulative_record"))
        if record is not None:
            anchors.append((idx, record))

    if len(anchors) < 2:
        return True

    for (prev_idx, prev_record), (curr_idx, curr_record) in zip(
        anchors,
        anchors[1:],
    ):
        delta_w = curr_record[0] - prev_record[0]
        delta_l = curr_record[1] - prev_record[1]
        if delta_w < 0 or delta_l < 0:
            return False

        wins = 0
        losses = 0
        for row in ordered[prev_idx + 1: curr_idx + 1]:
            decision = str(row.get("decision") or "").upper()
            if decision == "W":
                wins += 1
            elif decision == "L":
                losses += 1

        if (wins, losses) != (delta_w, delta_l):
            return False

    return True


def resolve_configured_pitching_record_chains(
    report: dict[str, Any],
    index: dict[str, Any],
) -> int:
    """Resolve remaining reviewed pitching collisions from cumulative W-L chains.

    Used only for the configured Bongé/Hönicke/El-Mahmoud split identities. Same-game
    rows are assigned one-to-one; a solution is accepted only when exactly one
    full assignment is consistent with each candidate's displayed record chain.
    """
    configured = {
        (
            spec["clean_name_key"],
            frozenset(spec["candidate_person_ids"]),
        )
        for spec in SEASON_TOTAL_SPLIT_IDENTITIES
    }

    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in report.get("rows") or []:
        if row.get("status") != "ambiguous" or row.get("role") != "pitching":
            continue

        clean_name_key = accentfold(
            str((row.get("parsed_name") or {}).get("clean_name") or "")
        )
        candidate_set = frozenset(
            pid for pid in (row.get("candidate_person_ids") or [])
            if isinstance(pid, int)
        )
        if (clean_name_key, candidate_set) not in configured:
            continue

        key = (
            clean_name_key,
            accentfold(str(row.get("boxscore_team") or "")),
            tuple(sorted(candidate_set)),
            tuple(sorted(
                gid for gid in (row.get("league_ids") or [])
                if isinstance(gid, int)
            )),
        )
        groups[key].append(row)

    import itertools
    changed = 0

    for key, ambiguous_rows in groups.items():
        clean_name_key, team_key, candidate_tuple, league_tuple = key
        candidate_ids = list(candidate_tuple)
        league_ids = set(league_tuple)

        auto_rows_by_person: dict[int, list[dict[str, Any]]] = {
            pid: [] for pid in candidate_ids
        }
        for row in report.get("rows") or []:
            if row.get("status") != "auto" or row.get("role") != "pitching":
                continue
            if row.get("person_id") not in auto_rows_by_person:
                continue
            if accentfold(str(row.get("boxscore_team") or "")) != team_key:
                continue
            if accentfold(
                str((row.get("parsed_name") or {}).get("clean_name") or "")
            ) != clean_name_key:
                continue
            row_leagues = {
                gid for gid in (row.get("league_ids") or [])
                if isinstance(gid, int)
            }
            if league_ids and row_leagues != league_ids:
                continue
            auto_rows_by_person[row["person_id"]].append(row)

        match_groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in ambiguous_rows:
            match_id = row.get("match_id")
            if not isinstance(match_id, int):
                match_groups = {}
                break
            match_groups[match_id].append(row)
        if not match_groups:
            continue

        ordered_groups = [
            match_groups[mid] for mid in sorted(match_groups)
        ]
        valid_solutions: list[dict[int, int]] = []

        def recurse(
            group_index: int,
            assignment: dict[int, int],
        ) -> None:
            if len(valid_solutions) >= 2:
                return

            if group_index >= len(ordered_groups):
                rows_by_person = {
                    pid: list(auto_rows_by_person[pid])
                    for pid in candidate_ids
                }
                for row in ambiguous_rows:
                    person_id = assignment.get(id(row))
                    if person_id is None:
                        return
                    rows_by_person[person_id].append(row)

                if all(
                    _pitching_record_chain_is_valid(rows_by_person[pid])
                    for pid in candidate_ids
                ):
                    valid_solutions.append(dict(assignment))
                return

            group_rows = ordered_groups[group_index]
            if len(group_rows) > len(candidate_ids):
                return

            for chosen_ids in itertools.permutations(
                candidate_ids,
                len(group_rows),
            ):
                next_assignment = dict(assignment)
                for row, person_id in zip(group_rows, chosen_ids):
                    next_assignment[id(row)] = person_id
                recurse(group_index + 1, next_assignment)

        recurse(0, {})

        if len(valid_solutions) != 1:
            continue

        solution = valid_solutions[0]
        for row in ambiguous_rows:
            person_id = solution.get(id(row))
            if person_id is None:
                continue
            if _set_auto_from_person(
                row,
                person_id,
                method="cumulative-pitching-record-chain",
                index=index,
            ):
                changed += 1

    return changed


def resolve_ambiguous_by_cumulative_totals(
    report: dict[str, Any],
    index: dict[str, Any],
) -> int:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)

    for row in report.get("rows") or []:
        if row.get("status") != "ambiguous":
            continue
        role = row.get("role")
        if role not in {"batting", "pitching"}:
            continue

        parsed = row.get("parsed_name") or {}
        key = (
            role,
            parsed.get("clean_name"),
            accentfold(str(row.get("boxscore_team") or "")),
            tuple(row.get("candidate_person_ids") or []),
        )
        groups[key].append(row)

    changed = 0

    for group_key, group_rows in groups.items():
        role = group_key[0]
        candidate_ids = list(group_rows[0].get("candidate_person_ids") or [])

        if role == "batting":
            solution = _solve_reverse_batting_group(
                rows=group_rows,
                candidate_ids=candidate_ids,
                index=index,
                report=report,
            )
            method = "reverse-cumulative-batting-totals"
        else:
            solution = _solve_reverse_pitching_group(
                rows=group_rows,
                candidate_ids=candidate_ids,
                index=index,
                report=report,
            )
            method = "reverse-cumulative-pitching-totals"

        if not solution:
            continue

        for row in group_rows:
            person_id = solution.get(id(row))
            if person_id is None:
                continue

            person = index["people"].get(person_id)
            if not person:
                continue

            row["status"] = "auto"
            row["method"] = method
            row["person_id"] = person_id
            row["canonical_name"] = person["canonical_name"]
            row["candidate_person_ids"] = [person_id]
            changed += 1

    return changed


def extract_batting_positions(raw_name: str) -> set[str]:
    return set(parse_position_sequence(raw_name))


def _set_auto_from_person(
    row: dict[str, Any],
    person_id: int,
    *,
    method: str,
    index: dict[str, Any],
) -> bool:
    person = index.get("people", {}).get(person_id)
    if not person:
        return False

    row["status"] = "auto"
    row["method"] = method
    row["person_id"] = person_id
    row["canonical_name"] = person["canonical_name"]
    row["candidate_person_ids"] = [person_id]
    return True


def resolve_ambiguous_by_role_linkage(
    report: dict[str, Any],
    index: dict[str, Any],
) -> int:
    """Use same-match pitcher positions and one-player-per-table elimination.

    This pass never guesses from position alone. It requires an already resolved
    person_id in the other role (batting/pitching), or a unique remaining
    candidate after another same-name row in the same table is resolved.
    """
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)

    for row in report.get("rows") or []:
        parsed = row.get("parsed_name") or {}
        clean_name = parsed.get("clean_name")
        match_id = row.get("match_id")
        team = accentfold(str(row.get("boxscore_team") or ""))
        if not clean_name or not isinstance(match_id, int) or not team:
            continue
        groups[(match_id, team, clean_name)].append(row)

    changed = 0
    progress = True

    while progress:
        progress = False

        for group_rows in groups.values():
            batting = [row for row in group_rows if row.get("role") == "batting"]
            pitching = [row for row in group_rows if row.get("role") == "pitching"]

            auto_pitching_ids = {
                row.get("person_id")
                for row in pitching
                if row.get("status") == "auto" and isinstance(row.get("person_id"), int)
            }
            auto_pitching_ids.discard(None)

            auto_pitcher_batting_ids = {
                row.get("person_id")
                for row in batting
                if (
                    row.get("status") == "auto"
                    and isinstance(row.get("person_id"), int)
                    and "p" in extract_batting_positions(str(row.get("raw_name") or ""))
                )
            }
            auto_pitcher_batting_ids.discard(None)

            # 1) An auto batting row explicitly marked as pitcher identifies
            #    a unique ambiguous pitching row candidate.
            ambiguous_pitching = [
                row for row in pitching if row.get("status") == "ambiguous"
            ]
            for row in ambiguous_pitching:
                candidates = set(row.get("candidate_person_ids") or [])
                linked = sorted(candidates.intersection(auto_pitcher_batting_ids))
                if len(linked) == 1:
                    if _set_auto_from_person(
                        row,
                        linked[0],
                        method="same-match-pitcher-role-link",
                        index=index,
                    ):
                        changed += 1
                        progress = True

            # Refresh after possible pitching resolutions.
            auto_pitching_ids = {
                row.get("person_id")
                for row in pitching
                if row.get("status") == "auto" and isinstance(row.get("person_id"), int)
            }
            auto_pitching_ids.discard(None)

            # 2) An auto pitching row identifies a unique ambiguous batting row
            #    that is explicitly marked with position p.
            ambiguous_pitcher_batting = [
                row
                for row in batting
                if (
                    row.get("status") == "ambiguous"
                    and "p" in extract_batting_positions(str(row.get("raw_name") or ""))
                )
            ]

            for person_id in sorted(auto_pitching_ids):
                matching_rows = [
                    row
                    for row in ambiguous_pitcher_batting
                    if person_id in set(row.get("candidate_person_ids") or [])
                ]
                if len(matching_rows) == 1:
                    row = matching_rows[0]
                    if _set_auto_from_person(
                        row,
                        person_id,
                        method="same-match-pitcher-role-link",
                        index=index,
                    ):
                        changed += 1
                        progress = True

            # 3) Within one batting/pitching table a physical person can only
            #    occupy one player row. If resolved same-name rows consume all
            #    but one candidate, assign the unique remainder.
            for role_rows in (batting, pitching):
                resolved_ids = {
                    row.get("person_id")
                    for row in role_rows
                    if row.get("status") == "auto" and isinstance(row.get("person_id"), int)
                }
                resolved_ids.discard(None)

                for row in role_rows:
                    if row.get("status") != "ambiguous":
                        continue
                    candidates = set(row.get("candidate_person_ids") or [])
                    remaining = sorted(candidates - resolved_ids)
                    if len(remaining) == 1:
                        if _set_auto_from_person(
                            row,
                            remaining[0],
                            method="same-match-candidate-elimination",
                            index=index,
                        ):
                            changed += 1
                            progress = True
                            resolved_ids.add(remaining[0])

    return changed


def _boxscore_identity_slug(clean_name: str) -> str:
    slug = accentfold(clean_name)
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug or "unknown"


def resolve_remaining_by_boxscore_identity(report: dict[str, Any]) -> int:
    """Resolve remaining Berlin same-name ambiguity by the user's chosen assumption.

    Assumption:
    within one season, the same Boxscore short name under the same Berlin club
    is treated as one player identity even when BSM canonical person IDs are
    still multiple candidates.

    Existing canonical auto rows in the same club/name group keep their
    person_id, but receive the same player_key so downstream game logs can
    treat the whole group as one person.
    """
    season = report.get("season")
    rows = report.get("rows") or []

    affected_groups: set[tuple[int, str]] = set()
    for row in rows:
        if row.get("status") != "ambiguous":
            continue
        club_id = row.get("berlin_club_id")
        clean_name = (row.get("parsed_name") or {}).get("clean_name")
        if isinstance(club_id, int) and clean_name:
            affected_groups.add((club_id, str(clean_name)))

    changed = 0

    for row in rows:
        club_id = row.get("berlin_club_id")
        clean_name = (row.get("parsed_name") or {}).get("clean_name")
        if not isinstance(club_id, int) or not clean_name:
            continue

        group_key = (club_id, str(clean_name))
        if group_key not in affected_groups:
            continue

        player_key = (
            f"bsm:{season}:club:{club_id}:"
            f"name:{_boxscore_identity_slug(str(clean_name))}"
        )
        row["player_key"] = player_key
        row["identity_source"] = "boxscore_short_name"
        row["identity_assumption"] = "same_short_name_same_berlin_club_is_same_player"
        row["position_sequence"] = (
            parse_position_sequence(str(row.get("raw_name") or ""))
            if row.get("role") == "batting"
            else []
        )
        row.update(parse_pitching_decision(str(row.get("raw_name") or "")))

        if row.get("status") == "ambiguous":
            row["status"] = "boxscore_identity"
            row["method"] = "same-berlin-club+boxscore-short-name-assumption"
            changed += 1

    return changed


def build_unresolved_summary(report: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}

    for row in report.get("rows") or []:
        status = row.get("status")
        if status == "auto":
            continue

        clean_name = (
            (row.get("parsed_name") or {}).get("clean_name")
            or row.get("raw_name")
            or ""
        )
        league_acronyms = tuple(row.get("league_acronyms") or [])
        candidates = tuple(row.get("candidate_person_ids") or [])
        key = (
            status,
            row.get("role"),
            row.get("boxscore_team"),
            clean_name,
            league_acronyms,
            candidates,
        )

        entry = grouped.setdefault(
            key,
            {
                "status": status,
                "role": row.get("role"),
                "boxscore_team": row.get("boxscore_team"),
                "clean_name": clean_name,
                "league_acronyms": list(league_acronyms),
                "candidate_person_ids": list(candidates),
                "occurrences": 0,
                "match_ids": [],
                "raw_names": [],
            },
        )
        entry["occurrences"] += 1

        match_id = row.get("match_id")
        if isinstance(match_id, int) and match_id not in entry["match_ids"]:
            entry["match_ids"].append(match_id)

        raw_name = row.get("raw_name")
        if raw_name and raw_name not in entry["raw_names"]:
            entry["raw_names"].append(raw_name)

    result = list(grouped.values())
    for entry in result:
        entry["match_ids"].sort()
        entry["raw_names"].sort()

    status_order = {
        "ambiguous": 0,
        "merged_identity": 1,
        "boxscore_identity": 2,
        "unmatched": 3,
        "review": 4,
        "canonical_scope_missing": 5,
    }
    return sorted(
        result,
        key=lambda row: (
            status_order.get(row["status"], 99),
            -row["occurrences"],
            str(row["boxscore_team"] or "").casefold(),
            str(row["clean_name"] or "").casefold(),
        ),
    )


def make_unresolved_text(report: dict[str, Any]) -> str:
    grouped = build_unresolved_summary(report)
    lines = [
        "===== BSM 2025 Unresolved Player Names =====",
        "",
        f"Unique unresolved groups: {len(grouped)}",
        "",
    ]

    for entry in grouped:
        leagues = ",".join(entry["league_acronyms"]) or "-"
        candidates = ",".join(map(str, entry["candidate_person_ids"])) or "-"
        matches = ",".join(map(str, entry["match_ids"])) or "-"
        lines.append(
            f"[{entry['status']}] {entry['clean_name']} "
            f"| role={entry['role']} | team={entry['boxscore_team']} "
            f"| league={leagues} | occurrences={entry['occurrences']} "
            f"| candidates={candidates} | matches={matches}"
        )

    lines.append("")
    return "\n".join(lines)


def make_text_report(report: dict[str, Any]) -> str:
    s = report["summary"]
    canonical = report["canonical"]
    lines = [
        "===== BSM 2025 Player Match Report =====",
        "",
        f"Canonical people: {canonical['people']}",
        f"Canonical group IDs: {', '.join(map(str, canonical['covered_group_ids'])) or '-'}",
        "",
        f"Boxscore files: {s['boxscore_files']}",
        f"Matches seen: {s['matches_seen']}",
        f"Matches with Berlin player rows: {s.get('matches_with_berlin_player_rows', 0)}",
        f"Matches outside canonical season scope: {s['matches_canonical_scope_missing']}",
        f"Boxscore player occurrences total: {s.get('boxscore_player_occurrences_total', s['player_occurrences'])}",
        f"Non-Berlin player occurrences skipped: {s.get('player_occurrences_non_berlin_skipped', 0)}",
        f"Berlin player occurrences: {s['player_occurrences']}",
        "",
        f"auto: {s['auto']}",
        f"merged_identity: {s.get('merged_identity', 0)}",
        f"review: {s['review']}",
        f"ambiguous: {s['ambiguous']}",
        f"unmatched: {s['unmatched']}",
        f"canonical_scope_missing: {s['canonical_scope_missing']}",
        f"resolved_by_identity_override: {s.get('resolved_by_identity_override', 0)}",
        f"resolved_by_cumulative_totals: {s.get('resolved_by_cumulative_totals', 0)}",
        f"resolved_by_season_total_constraints: {s.get('resolved_by_season_total_constraints', 0)}",
        f"resolved_by_role_linkage: {s.get('resolved_by_role_linkage', 0)}",
        f"resolved_by_pitching_record_chain: {s.get('resolved_by_pitching_record_chain', 0)}",
        f"Canonical auto rate: {s['auto_rate_percent']:.2f}%",
        f"Resolved rate: {s.get('resolved_rate_percent', s['auto_rate_percent']):.2f}%",
        "",
        "v8 identity policy: Bongé / Hönicke / El-Mahmoud are separate people; no short-name merge is allowed.",
        "",
        "Interpretation:",
        "- auto: safe to connect to canonical person_id.",
        "- merged_identity: legacy compatibility counter; v8 expects this to remain 0.",
        "- review: one plausible person, but team/group evidence is incomplete.",
        "- ambiguous: multiple plausible people; manual review required.",
        "- unmatched: no canonical surname+initial candidate found.",
        "- canonical_scope_missing: this Boxscore league is not represented in the current 2025 season JSON.",
        "",
    ]
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Match BSM Boxscore short names to 2025 season person IDs."
    )
    parser.add_argument("--season-file", type=Path)
    parser.add_argument("--candidate-file", type=Path)
    parser.add_argument("--boxscore-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--limit", type=int)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    default_season, default_candidate, default_boxscore_dir = discover_defaults()

    season_file = args.season_file or default_season
    candidate_file = args.candidate_file or default_candidate
    boxscore_dir = args.boxscore_dir or default_boxscore_dir

    missing = []
    if not season_file or not season_file.exists():
        missing.append("season file (data/seasons/2025.json)")
    if not candidate_file or not candidate_file.exists():
        missing.append("candidate_matches.json")
    if not boxscore_dir or not boxscore_dir.exists():
        missing.append("boxscores_parsed directory")

    if missing:
        print("ERROR: Missing " + ", ".join(missing), file=sys.stderr)
        print("Use --season-file / --candidate-file / --boxscore-dir explicitly.", file=sys.stderr)
        return 1

    season_data = load_json(season_file)
    candidate_matches = load_json(candidate_file)
    boxscore_files = sorted(boxscore_dir.glob("*.json"))
    if args.limit is not None:
        boxscore_files = boxscore_files[:max(0, args.limit)]

    output_dir = args.output_dir or candidate_file.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    report = build_match_report(
        season_data=season_data,
        candidate_matches=candidate_matches,
        boxscore_files=boxscore_files,
    )

    json_path = output_dir / "player_match_report_v8.json"
    text_path = output_dir / "player_match_report_v8.txt"
    unresolved_json_path = output_dir / "player_match_unresolved_v8.json"
    unresolved_text_path = output_dir / "player_match_unresolved_v8.txt"

    save_json(json_path, report)
    text_path.write_text(make_text_report(report), encoding="utf-8")
    save_json(unresolved_json_path, build_unresolved_summary(report))
    unresolved_text_path.write_text(
        make_unresolved_text(report),
        encoding="utf-8",
    )

    print(make_text_report(report), end="")
    print(f"JSON report: {json_path}")
    print(f"Text report: {text_path}")
    print(f"Unresolved JSON: {unresolved_json_path}")
    print(f"Unresolved text: {unresolved_text_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
