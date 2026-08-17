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
- tests/bsm_season_data/2025_discovery_v2/player_match_report.json
- tests/bsm_season_data/2025_discovery_v2/player_match_report.txt
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


POSITION_TOKEN = r"(?:p|c|1b|2b|3b|ss|lf|cf|rf|dh|ph|pr|of|if|dp|flex)"
POSITION_RE = re.compile(
    rf"\s+{POSITION_TOKEN}(?:[/,\-]{POSITION_TOKEN})*\s*$",
    re.IGNORECASE,
)
DECISION_RE = re.compile(r"\s*\([^)]*\)\s*$")
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


def build_canonical_index(season_data: dict[str, Any]) -> dict[str, Any]:
    people: dict[int, dict[str, Any]] = {}
    covered_group_ids: set[int] = set()

    # Aggregate batting/pitching roles into the same team/group context.
    context_maps: dict[int, dict[tuple[Any, ...], dict[str, Any]]] = defaultdict(dict)

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
                        "roles": [],
                    }
                    context_maps[person_id][context_key] = existing

                if role not in existing["roles"]:
                    existing["roles"].append(role)
                    existing["roles"].sort()

    contexts_by_person = {
        person_id: list(context_map.values())
        for person_id, context_map in context_maps.items()
    }

    return {
        "people": people,
        "contexts_by_person": contexts_by_person,
        "covered_group_ids": covered_group_ids,
    }


def _person_ids_matching_name(
    parsed: dict[str, str | None],
    index: dict[str, Any],
) -> list[int]:
    surname_key = accentfold(str(parsed.get("surname") or ""))
    initial = parsed.get("initial")
    initial_key = accentfold(str(initial or ""))[:1]

    result: list[int] = []
    for person_id, person in index["people"].items():
        if person["surname_key"] != surname_key:
            continue
        if initial_key and person["initial_key"] != initial_key:
            continue
        result.append(person_id)
    return sorted(set(result))


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

    name_candidates = _person_ids_matching_name(parsed, index)
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
            "group+team+surname+initial",
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
                    "group+team+role+surname+initial",
                    parsed,
                    index,
                )
            if len(role_strong) > 1:
                strong = role_strong
                method = "group+team+role+surname+initial"
            else:
                method = "group+team+surname+initial"
        else:
            method = "group+team+surname+initial"

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
            "team+surname+initial",
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
                    "team+role+surname+initial",
                    parsed,
                    index,
                )
            if len(role_team) > 1:
                team_candidates = role_team
                method = "team+role+surname+initial"
            else:
                method = "team+surname+initial"
        else:
            method = "team+surname+initial"

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
            "method": "group+surname+initial",
            "person_id": pid,
            "canonical_name": index["people"][pid]["canonical_name"],
            "candidate_person_ids": [pid],
            "parsed_name": parsed,
        }
    if len(group_candidates) > 1:
        method = "group+surname+initial"
        if role:
            role_group = sorted({
                pid for pid in group_candidates
                if _person_has_group_role(pid, league_id_set, role, index)
            })
            if len(role_group) == 1:
                pid = role_group[0]
                return {
                    "status": "review",
                    "method": "group+role+surname+initial",
                    "person_id": pid,
                    "canonical_name": index["people"][pid]["canonical_name"],
                    "candidate_person_ids": [pid],
                    "parsed_name": parsed,
                }
            if len(role_group) > 1:
                group_candidates = role_group
                method = "group+role+surname+initial"

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
            "method": "surname+initial",
            "person_id": pid,
            "canonical_name": index["people"][pid]["canonical_name"],
            "candidate_person_ids": [pid],
            "parsed_name": parsed,
        }

    return {
        "status": "ambiguous",
        "method": "surname+initial",
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

    rows: list[dict[str, Any]] = []
    status_counter: Counter[str] = Counter()
    matches_scope_missing: set[int] = set()
    matches_seen: set[int] = set()

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
                "raw_name": occurrence["raw_name"],
                "stats": occurrence["stats"],
                **matched,
            })

    total = len(rows)
    auto = status_counter.get("auto", 0)
    return {
        "season": season_data.get("season"),
        "canonical": {
            "people": len(index["people"]),
            "covered_group_ids": sorted(index["covered_group_ids"]),
        },
        "summary": {
            "boxscore_files": len(boxscore_files),
            "matches_seen": len(matches_seen),
            "matches_canonical_scope_missing": len(matches_scope_missing),
            "player_occurrences": total,
            "auto": auto,
            "review": status_counter.get("review", 0),
            "ambiguous": status_counter.get("ambiguous", 0),
            "unmatched": status_counter.get("unmatched", 0),
            "canonical_scope_missing": status_counter.get("canonical_scope_missing", 0),
            "auto_rate_percent": round((auto / total * 100) if total else 0.0, 2),
        },
        "rows": rows,
    }


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
        "unmatched": 1,
        "review": 2,
        "canonical_scope_missing": 3,
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
        f"Matches outside canonical season scope: {s['matches_canonical_scope_missing']}",
        f"Player occurrences: {s['player_occurrences']}",
        "",
        f"auto: {s['auto']}",
        f"review: {s['review']}",
        f"ambiguous: {s['ambiguous']}",
        f"unmatched: {s['unmatched']}",
        f"canonical_scope_missing: {s['canonical_scope_missing']}",
        f"Auto rate: {s['auto_rate_percent']:.2f}%",
        "",
        "Interpretation:",
        "- auto: safe to connect to person_id.",
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

    json_path = output_dir / "player_match_report_v2.json"
    text_path = output_dir / "player_match_report_v2.txt"
    unresolved_json_path = output_dir / "player_match_unresolved_v2.json"
    unresolved_text_path = output_dir / "player_match_unresolved_v2.txt"

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
