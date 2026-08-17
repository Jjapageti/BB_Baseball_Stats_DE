#!/usr/bin/env python3
"""BSM 2025 BSVBB 전체 시즌 + BSVBB 참가 광역대회 데이터를 수집한다.

이 버전은 Berlin Sluggers(Club-ID 492)만 기준으로 리그를 찾지 않는다.
먼저 ``fetch_2025_bsvbb_probe_v2.py``가 만든 discovery 결과를 입력으로 사용한다.

입력
----
- candidate_leagues.json
- candidate_matches.json

선택 규칙
---------
1. ``local_bsvbb`` 리그는 전부 시즌 데이터에 포함한다.
2. ``overregional_candidate`` 리그도 BSVBB 선수 identity/person_id 연결을 위해
   리그 전체 팀/선수 통계를 수집한다.
3. 동일 경기에서 league/second_league로 함께 연결된 그룹은 같은 logical league로
   병합한다(예: 2025 Landesliga DivA + DivB).
4. Baseball/Softball, 성인/청소년/Schüler/Coach Pitch/DM 등을 모두 허용한다.

출력
----
- <project>/bsm_season_data/2025/season_2025.json
- <project>/data/seasons/2025.json
- <project>/bsm_season_data/2025/fetch_report.txt
- <project>/bsm_season_data/2025/discovery.json
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode


def _find_project_root() -> Path:
    """Find BB_Baseball_Stats_DE regardless of running from root/tests/fetchers."""
    script_dir = Path(__file__).resolve().parent
    candidates = [Path.cwd().resolve(), script_dir, *script_dir.parents]
    for candidate in candidates:
        if (
            (candidate / "league_data_fetcher.py").exists()
            and (candidate / "landesliga_data_fetcher_vscode.py").exists()
        ):
            return candidate
    # Common case: script is inside tests and helpers live one level up.
    if Path.cwd().name.casefold() == "tests":
        return Path.cwd().resolve().parent
    return Path.cwd().resolve()


PROJECT_ROOT = _find_project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from league_data_fetcher import (
    BASE_URL,
    fetch_discovery_payloads,
    fetch_json,
    fetch_team_dataset,
    write_json,
)
from landesliga_data_fetcher_vscode import (
    annotate_match_sources,
    as_int,
    compute_combined_standings,
    dedupe_matches,
    dedupe_player_rows,
    enrich_discovered_teams,
    extract_match_teams,
    merge_group_teams,
    nonempty,
    unique_sorted,
)


# ---------------------------------------------------------------------------
# 사용자 설정
# ---------------------------------------------------------------------------
SEASON = 2025
SCRIPT_VERSION = "2026-08-14-bsvbb-full-v5"

# 하위 호환용 메타데이터. 리그 선택 기준으로는 더 이상 사용하지 않는다.
TARGET_CLUB_ID = 492
TARGET_CLUB_NAME = "Berlin Sluggers"

PUBLISH_TO_SITE_DATA = True

OUTPUT_ROOT = PROJECT_ROOT / "bsm_season_data"
OUTPUT_DIR = OUTPUT_ROOT / str(SEASON)
SITE_OUTPUT = PROJECT_ROOT / "data" / "seasons" / f"{SEASON}.json"

DISCOVERY_RELATIVE_DIRS = (
    Path("tests") / "bsm_season_data" / "2025_discovery_v2",
    Path("bsm_season_data") / "2025_discovery_v2",
)

TIMEOUT = 35.0
RETRIES = 3
REQUEST_DELAY = 0.15

LEVEL_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("2-bundesliga", ("2. baseball-bundesliga", "2. bundesliga", "2bl")),
    ("deutschlandpokal", ("deutschlandpokal",)),
    ("coach-pitch", ("coach pitch", "coach-pitch", "copi")),
    ("schueler", ("schüler", "schueler", "schbb")),
    ("juniorinnen", ("juniorinnen", "junorinnen", "junsb")),
    ("junioren", ("junioren", "junbb")),
    ("jugend", ("jugend", "juga", "jugbb")),
    ("dm", ("dm ", "deutsche meisterschaft")),
    ("bundesliga", ("bundesliga",)),
    ("regionalliga", ("regionalliga",)),
    ("verbandsliga", ("verbandsliga", "vlbb", "vlsb")),
    ("landesliga", ("landesliga", "llbb")),
    ("bezirksliga", ("bezirksliga", "vezirksliga")),
)

POSTSEASON_TERMS = (
    "playoff",
    "playoffs",
    "play-off",
    "playdown",
    "playdowns",
    "relegation",
    "aufstieg",
    "abstieg",
    "finalrunde",
    "meisterrunde",
    "pokal",
)

LEVEL_ORDER = {
    "2-bundesliga": 10,
    "bundesliga": 20,
    "deutschlandpokal": 25,
    "regionalliga": 30,
    "verbandsliga": 40,
    "landesliga": 50,
    "bezirksliga": 60,
    "junioren": 70,
    "juniorinnen": 71,
    "jugend": 80,
    "schueler": 90,
    "coach-pitch": 100,
    "dm": 110,
}


# ---------------------------------------------------------------------------
# 기본 유틸
# ---------------------------------------------------------------------------
def text(value: Any) -> str:
    return str(value or "").strip()


def safe_slug(value: Any) -> str:
    result = text(value).casefold()
    result = (
        result.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    result = re.sub(r"[^a-z0-9]+", "-", result)
    return result.strip("-") or "league"


def build_season_matches_url() -> str:
    query = urlencode(
        {
            "compact": "true",
            "show_all": "true",
            "filters[seasons][]": str(SEASON),
        }
    )
    return f"{BASE_URL.rstrip('/')}/matches.json?{query}"


def iter_matches(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "matches", "rows", "items"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


def federation_id_from_match(match: dict[str, Any]) -> int | None:
    federation = match.get("federation")
    if isinstance(federation, dict):
        return as_int(federation.get("id"))
    return as_int(match.get("federation_id"))


def league_objects_from_match(match: dict[str, Any]) -> list[dict[str, Any]]:
    """실제 경기 소속인 ``league``와 ``second_league``만 반환한다.

    ``extra_rating_league`` 계열은 별도 평가표용 연결일 수 있으므로 시즌
    리그 탐색과 순위 병합 대상에서 제외한다.
    """
    result: list[dict[str, Any]] = []
    for key in ("league", "second_league"):
        value = match.get(key)
        if isinstance(value, dict) and as_int(value.get("id")) is not None:
            row = copy.deepcopy(value)
            row["source_field"] = key
            result.append(row)
    return result


def club_ids_from_entry(entry: Any) -> set[int]:
    """league_entry의 실제 club 객체에서만 Club ID를 읽는다.

    team.id, league_entry.id, field.club 등 다른 종류의 ID는 절대로 Club ID로
    취급하지 않는다. 과거 코드의 재귀 탐색은 team.id가 우연히 492인 경우를
    Berlin Sluggers로 오인할 수 있었다.
    """
    if not isinstance(entry, dict):
        return set()

    ids: set[int] = set()

    def add_club(candidate: Any) -> None:
        if not isinstance(candidate, dict):
            return
        candidate_type = text(candidate.get("type")).casefold()
        # BSM 응답에 type이 생략되는 경우도 있으므로 club 위치에 있는 객체는 허용한다.
        if candidate_type and candidate_type != "club":
            return
        club_id = as_int(candidate.get("id"))
        if club_id is not None:
            ids.add(club_id)

    def add_club_list(candidates: Any) -> None:
        if isinstance(candidates, list):
            for candidate in candidates:
                add_club(candidate)

    add_club(entry.get("club"))
    add_club_list(entry.get("clubs"))

    team = entry.get("team") if isinstance(entry.get("team"), dict) else {}
    add_club(team.get("club"))
    add_club_list(team.get("clubs"))
    return ids


def match_contains_target_club(match: dict[str, Any]) -> bool:
    """홈/원정 참가 엔트리에 Club ID 492가 실제로 있는지 확인한다.

    이름에 ``Sluggers``가 들어간다는 이유만으로는 선택하지 않는다. 이름 폴백은
    다른 지역의 동명 팀을 섞을 위험이 있으므로 사용하지 않는다.
    """
    for side in ("home_league_entry", "away_league_entry"):
        if TARGET_CLUB_ID in club_ids_from_entry(match.get(side)):
            return True
    return False


# ---------------------------------------------------------------------------
# 리그 분류 / discovery 입력
# ---------------------------------------------------------------------------
def league_search_text(group: dict[str, Any]) -> str:
    return " ".join(
        [
            text(group.get("name")),
            text(group.get("acronym")),
            text(group.get("human_sport")),
        ]
    ).casefold()


def classify_level(group: dict[str, Any]) -> str:
    haystack = league_search_text(group)
    compact_acronym = re.sub(r"[^a-z0-9]", "", text(group.get("acronym")).casefold())

    # DM before generic Jugend/Junioren when acronym/name clearly says DM.
    if "dm " in haystack or compact_acronym.startswith(("juggr", "jugpo", "junsbgr", "junsbpo", "jungr", "junpo", "schgr", "schpo")):
        return "dm"

    for level, patterns in LEVEL_PATTERNS:
        if any(pattern in haystack for pattern in patterns):
            return level
    return "other"


def classify_stage(group: dict[str, Any]) -> str:
    haystack = league_search_text(group)
    compact = re.sub(r"[^a-z0-9]", "", haystack)
    acronym = re.sub(r"[^a-z0-9]", "", text(group.get("acronym")).casefold())

    postseason = any(term.replace("-", "") in compact for term in POSTSEASON_TERMS)
    acronym_postseason = bool(
        re.search(r"(?:po|pof|playoff|pd|playdown|rel|relegation)$", acronym)
    )
    return "postseason" if postseason or acronym_postseason else "regular"


def normalize_family_name(name: Any) -> str:
    value = text(name).casefold()
    value = (
        value.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    value = re.sub(r"\b(?:division|div\.?|gruppe|group)\s*[-:]?\s*[a-z0-9]+\b", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" -_/()")
    return value


def group_family_key(group: dict[str, Any]) -> tuple[Any, ...]:
    level = classify_level(group)
    stage = classify_stage(group)
    family_name = normalize_family_name(group.get("name"))
    sport = text(group.get("sport")).casefold()
    scope = text(group.get("scope")).casefold()

    if not family_name:
        family_name = re.sub(
            r"(?:div|gruppe|group)[a-z0-9]+$",
            "",
            text(group.get("acronym")).casefold(),
        )

    return sport, scope, level, stage, family_name


def _candidate_group_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    group_id = as_int(row.get("league_id"))
    if group_id is None:
        return None
    group = {
        "id": group_id,
        "name": nonempty(row.get("league_name")),
        "acronym": nonempty(row.get("league_acronym")),
        "sport": nonempty(row.get("sport")),
        "human_sport": nonempty(row.get("human_sport")),
        "scope": nonempty(row.get("scope")) or "unknown",
        "source_fields": sorted(set(row.get("league_sources", []) or [])),
        "match_count": as_int(row.get("total_match_count")) or 0,
        "seed_match_count": as_int(row.get("seed_match_count")) or 0,
        "bsvbb_club_count": as_int(row.get("bsvbb_club_count")) or 0,
        "bsvbb_clubs": copy.deepcopy(row.get("bsvbb_clubs", []) or []),
        "linked_group_ids": [],
    }
    group["level"] = classify_level(group)
    group["stage"] = classify_stage(group)
    group["family_key"] = list(group_family_key(group))
    return group


def build_group_catalog_from_discovery(
    candidate_leagues: list[dict[str, Any]],
    candidate_matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build exact 2025 BSVBB catalog from probe-v2 output.

    No substring discovery and no Sluggers-only filter is performed here.
    """
    by_id: dict[int, dict[str, Any]] = {}

    for row in candidate_leagues:
        if not isinstance(row, dict):
            continue
        group = _candidate_group_from_row(row)
        if group is not None:
            by_id[group["id"]] = group

    # Explicit league/second_league co-occurrence creates a merge edge.
    for match in candidate_matches:
        if not isinstance(match, dict):
            continue
        ids = unique_sorted(
            as_int(ref.get("league_id"))
            for ref in (match.get("candidate_leagues") or [])
            if isinstance(ref, dict)
        )
        ids = [group_id for group_id in ids if group_id in by_id]
        if len(ids) < 2:
            continue

        for left in ids:
            for right in ids:
                if left == right:
                    continue
                if right not in by_id[left]["linked_group_ids"]:
                    by_id[left]["linked_group_ids"].append(right)

    result = list(by_id.values())
    for row in result:
        row["linked_group_ids"] = unique_sorted(row.get("linked_group_ids", []))
        row["family_key"] = list(group_family_key(row))

    return sorted(
        result,
        key=lambda row: (
            0 if row.get("scope") == "local_bsvbb" else 1,
            LEVEL_ORDER.get(row.get("level"), 999),
            1 if row.get("stage") == "postseason" else 0,
            row["id"],
        ),
    )


def select_target_groups(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Probe-v2 already performed the 2025 allow-list decision; keep all 26 groups."""
    return [
        row
        for row in catalog
        if row.get("scope") in {"local_bsvbb", "overregional_candidate"}
    ]


def build_logical_leagues(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge only explicitly linked compatible source groups.

    Example: Landesliga DivA 6054 + DivB 6055.
    """
    by_id = {row["id"]: row for row in groups}
    components: list[list[dict[str, Any]]] = []
    visited: set[int] = set()

    for start_id in sorted(by_id):
        if start_id in visited:
            continue
        start_group = by_id[start_id]
        component_ids: set[int] = set()
        queue = [start_id]

        while queue:
            group_id = queue.pop()
            if group_id in component_ids:
                continue
            group = by_id.get(group_id)
            if group is None:
                continue

            # Do not merge across sport, scope, level, or stage.
            if group.get("sport") != start_group.get("sport"):
                continue
            if group.get("scope") != start_group.get("scope"):
                continue
            if group.get("level") != start_group.get("level"):
                continue
            if group.get("stage") != start_group.get("stage"):
                continue

            component_ids.add(group_id)
            for linked_id in group.get("linked_group_ids", []) or []:
                if linked_id in by_id and linked_id not in component_ids:
                    queue.append(linked_id)

        visited.update(component_ids)
        components.append([by_id[group_id] for group_id in sorted(component_ids)])

    logical: list[dict[str, Any]] = []
    used_keys: Counter[str] = Counter()

    for source_groups in components:
        first = source_groups[0]
        level = first.get("level") or "other"
        stage = first.get("stage") or "regular"
        scope = first.get("scope") or "unknown"
        sport = first.get("sport") or ""
        human_sport = first.get("human_sport") or ""
        names = [text(row.get("name")) for row in source_groups if text(row.get("name"))]
        display_name = Counter(names).most_common(1)[0][0] if names else level.title()
        base_key = safe_slug(f"{sport}-{scope}-{level}-{stage}-{display_name}")
        used_keys[base_key] += 1
        key = base_key if used_keys[base_key] == 1 else f"{base_key}-{used_keys[base_key]}"

        logical.append(
            {
                "key": key,
                "name": display_name,
                "level": level,
                "stage": stage,
                "scope": scope,
                "sport": sport,
                "human_sport": human_sport,
                "merged": len(source_groups) > 1,
                "source_groups": [
                    {
                        "id": row["id"],
                        "name": row.get("name"),
                        "acronym": row.get("acronym"),
                        "sport": row.get("sport"),
                        "human_sport": row.get("human_sport"),
                        "scope": row.get("scope"),
                        "match_count": row.get("match_count", 0),
                        "seed_match_count": row.get("seed_match_count", 0),
                        "bsvbb_club_count": row.get("bsvbb_club_count", 0),
                        "source_fields": row.get("source_fields", []),
                        "linked_group_ids": row.get("linked_group_ids", []),
                    }
                    for row in source_groups
                ],
            }
        )

    return sorted(
        logical,
        key=lambda row: (
            0 if row["scope"] == "local_bsvbb" else 1,
            LEVEL_ORDER.get(row["level"], 999),
            1 if row["stage"] == "postseason" else 0,
            row["name"].casefold(),
            row["key"],
        ),
    )


def find_discovery_inputs() -> tuple[Path, Path]:
    candidates: list[Path] = []
    for relative in DISCOVERY_RELATIVE_DIRS:
        candidates.append(PROJECT_ROOT / relative)

    # When the script itself lives in tests, also inspect its sibling output.
    script_dir = Path(__file__).resolve().parent
    candidates.append(script_dir / "bsm_season_data" / "2025_discovery_v2")

    for directory in candidates:
        league_file = directory / "candidate_leagues.json"
        match_file = directory / "candidate_matches.json"
        if league_file.exists() and match_file.exists():
            return league_file, match_file

    checked = "\n".join(f"  - {path}" for path in candidates)
    raise FileNotFoundError(
        "candidate_leagues.json / candidate_matches.json을 찾지 못했습니다.\n"
        "먼저 fetch_2025_bsvbb_probe_v2.py --no-boxscores 를 실행하세요.\n"
        f"확인한 위치:\n{checked}"
    )


# ---------------------------------------------------------------------------
# 리그 전체 데이터 수집
# ---------------------------------------------------------------------------
def add_context_to_players(
    rows: list[dict[str, Any]], league_meta: dict[str, Any]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    context = {
        "season": SEASON,
        "key": league_meta["key"],
        "name": league_meta["name"],
        "level": league_meta["level"],
        "stage": league_meta["stage"],
        "scope": league_meta.get("scope"),
        "sport": league_meta.get("sport"),
    }
    for row in rows:
        cloned = copy.deepcopy(row)
        cloned["season"] = SEASON
        cloned["league_context"] = copy.deepcopy(context)
        result.append(cloned)
    return result


def fetch_logical_league(
    logical: dict[str, Any],
    league_index: int,
    league_total: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    league_dir = OUTPUT_DIR / "raw" / logical["key"]
    league_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 78)
    print(f"[{league_index}/{league_total}] {logical['name']} ({logical['stage']})")
    print("Quellgruppen: " + ", ".join(
        f"{g.get('acronym') or '-'}={g['id']}"
        f"[Sluggers-Spiele={g.get('target_match_count', 0)};"
        f"Quelle={'+'.join(g.get('target_source_fields', [])) or '-'}]"
        for g in logical["source_groups"]
    ))

    team_groups: list[list[dict[str, Any]]] = []
    match_groups: list[list[dict[str, Any]]] = []
    group_reports: list[dict[str, Any]] = []

    for source in logical["source_groups"]:
        group_id = source["id"]
        group_acronym = source.get("acronym") or str(group_id)
        group = {
            "id": group_id,
            "acronym": group_acronym,
            "name": source.get("name") or logical["name"],
            "sport": source.get("sport") or logical.get("sport"),
            "human_sport": source.get("human_sport") or logical.get("human_sport"),
        }
        group_raw_dir = league_dir / f"{group_acronym}_{group_id}"
        discovery, discovered_teams, failures = fetch_discovery_payloads(
            base_url=BASE_URL,
            league_id=group_id,
            raw_dir=group_raw_dir,
            timeout=TIMEOUT,
            retries=RETRIES,
            delay=REQUEST_DELAY,
        )

        matches = annotate_match_sources(discovery.get("group_matches"), group_id)
        teams_from_discovery = enrich_discovered_teams(discovered_teams, group)
        teams_from_matches = extract_match_teams(matches, group)
        group_teams = merge_group_teams(teams_from_discovery, teams_from_matches)

        team_groups.append(group_teams)
        match_groups.append(matches)
        group_reports.append(
            {
                "id": group_id,
                "acronym": group_acronym,
                "teams": len(group_teams),
                "matches": len(matches),
                "failures": failures,
            }
        )
        print(f"  - {group_acronym} ({group_id}): teams={len(group_teams)}, matches={len(matches)}")

    teams = merge_group_teams(*team_groups)
    matches = dedupe_matches(*match_groups)
    standings = compute_combined_standings(matches, teams)

    batting_rows: list[dict[str, Any]] = []
    pitching_rows: list[dict[str, Any]] = []
    team_fetches: list[dict[str, Any]] = []
    total_requests = len(teams) * 2
    request_no = 0

    for team in teams:
        for dataset in ("batting", "pitching"):
            request_no += 1
            print(
                f"    [{request_no}/{total_requests}] "
                f"{team.get('name')} ({team['id']}) {dataset}"
            )
            rows, fetch_report = fetch_team_dataset(
                base_url=BASE_URL,
                league_entry=team,
                dataset=dataset,
                raw_dir=league_dir / "teams",
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
    batting_rows = add_context_to_players(batting_rows, logical)
    pitching_rows = add_context_to_players(pitching_rows, logical)

    played_matches = sum(
        1
        for match in matches
        if match.get("state") in {"played", "manually_valued"}
        and as_int(match.get("home_runs")) is not None
        and as_int(match.get("away_runs")) is not None
    )

    league_payload = {
        **copy.deepcopy(logical),
        "season": SEASON,
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

    report = {
        "league": {
            key: copy.deepcopy(league_payload[key])
            for key in ("key", "name", "level", "stage", "scope", "sport", "human_sport", "merged", "source_groups", "counts")
        },
        "groups": group_reports,
        "team_fetches": team_fetches,
    }
    return league_payload, report


# ---------------------------------------------------------------------------
# 보고서
# ---------------------------------------------------------------------------
def render_report(report: dict[str, Any]) -> str:
    lines = [
        f"BSM SEASON {SEASON} BSVBB FULL FETCH REPORT",
        "=" * 82,
        f"Erstellt          : {report['generated_at']}",
        f"Saison            : {report['season']}",
        f"Discovery-Ligen   : {len(report['selected_groups'])} Quellgruppen",
        f"Gespeicherte Ligen: {len(report['leagues'])}",
        "",
        "[AUSGEWÄHLTE QUELLGRUPPEN]",
    ]

    for group in report["selected_groups"]:
        lines.append(
            f"- {group.get('acronym') or '-':<16} id={group['id']:<6} "
            f"scope={group.get('scope'):<24} "
            f"level={group.get('level'):<18} stage={group.get('stage'):<10} "
            f"matches={group.get('match_count', 0):<4} "
            f"name={group.get('name')}"
        )

    lines.extend(["", "[GESPEICHERTE LIGEN]"])
    for league in report["leagues"]:
        meta = league["league"]
        counts = meta["counts"]
        source_ids = ", ".join(str(g["id"]) for g in meta["source_groups"])
        lines.append(
            f"- {meta['name']} | scope={meta.get('scope')} | sport={meta.get('sport')} "
            f"| key={meta['key']} | source={source_ids} | "
            f"teams={counts['teams']} matches={counts['matches']} "
            f"batters={counts['batters']} pitchers={counts['pitchers']}"
        )
        for group in league["groups"]:
            for failure in group.get("failures", []):
                lines.append(
                    f"    [FAIL] {group['acronym']} {failure.get('label')}: {failure.get('error')}"
                )

    lines.extend(
        [
            "",
            "[AUSGABE]",
            f"- {report['output_files']['season_json']}",
            f"- {report['output_files']['discovery_json']}",
            f"- {report['output_files']['report_json']}",
            f"- {report['output_files']['report_text']}",
            f"- {report['output_files'].get('site_json') or '(Site-Kopie deaktiviert)'}",
            "",
            f"season_{SEASON}.json enthält BSVBB lokale Ligen plus ausgewählte überregionale Ligen.",
        ]
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
def run(*, fetch: bool = False) -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SITE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    print(f"[Fetcher-Version] {SCRIPT_VERSION}")
    print(f"[Project-Root] {PROJECT_ROOT}")
    print("[Scope] BSVBB local leagues + BSVBB-related overregional candidates")

    print("[1/4] probe-v2 discovery 파일 읽기")
    candidate_league_path, candidate_match_path = find_discovery_inputs()
    print(f"      leagues : {candidate_league_path}")
    print(f"      matches : {candidate_match_path}")

    candidate_leagues = json.loads(candidate_league_path.read_text(encoding="utf-8"))
    candidate_matches = json.loads(candidate_match_path.read_text(encoding="utf-8"))
    if not isinstance(candidate_leagues, list) or not isinstance(candidate_matches, list):
        raise TypeError("candidate_leagues.json / candidate_matches.json 형식이 list가 아닙니다.")

    catalog = build_group_catalog_from_discovery(candidate_leagues, candidate_matches)
    selected_groups = select_target_groups(catalog)
    logical_leagues = build_logical_leagues(selected_groups)

    discovery_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season": SEASON,
        "source_files": {
            "candidate_leagues": str(candidate_league_path.resolve()),
            "candidate_matches": str(candidate_match_path.resolve()),
        },
        "scope": {
            "local": "local_bsvbb",
            "overregional": "overregional_candidate",
        },
        "selected_groups": selected_groups,
        "logical_leagues": logical_leagues,
    }
    discovery_path = OUTPUT_DIR / "discovery.json"
    write_json(discovery_path, discovery_payload)

    print(
        f"      {len(selected_groups)} source groups -> "
        f"{len(logical_leagues)} logical leagues"
    )
    print(
        "      local="
        f"{sum(1 for row in selected_groups if row.get('scope') == 'local_bsvbb')} "
        "overregional="
        f"{sum(1 for row in selected_groups if row.get('scope') == 'overregional_candidate')}"
    )

    if not selected_groups:
        print(f"      {SEASON} discovery 대상 리그가 없습니다.")
        return 2

    print("[2/4] 선택 리그 확인")
    for group in selected_groups:
        print(
            f"      - {group.get('acronym') or '-'} id={group['id']} "
            f"| {group.get('scope')} | {group.get('sport')} "
            f"| {group.get('level')} | {group.get('stage')} "
            f"| {group.get('name')}"
        )

    if not fetch:
        print()
        print("[DRY-RUN] discovery 확인만 완료했습니다.")
        print("          실제 BSM 팀/선수 데이터 수집은 --fetch 옵션으로 실행하세요.")
        print(f"          discovery: {discovery_path}")
        return 0

    print(f"[3/4] 전체 리그 데이터 수집 ({len(logical_leagues)}개)")
    leagues: list[dict[str, Any]] = []
    league_reports: list[dict[str, Any]] = []
    for index, logical in enumerate(logical_leagues, start=1):
        payload, league_report = fetch_logical_league(logical, index, len(logical_leagues))
        leagues.append(payload)
        league_reports.append(league_report)

    generated_at = datetime.now(timezone.utc).isoformat()
    season_payload = {
        "schema_version": 3,
        "generated_at": generated_at,
        "season": SEASON,
        # Keep legacy field so existing frontend code reading target_club does not crash.
        "target_club": {"id": TARGET_CLUB_ID, "name": TARGET_CLUB_NAME, "legacy_metadata_only": True},
        "scope": {
            "type": "bsvbb_full",
            "description": "BSVBB local leagues plus BSVBB-related overregional competitions",
        },
        "counts": {
            "leagues": len(leagues),
            "source_groups": len(selected_groups),
            "teams": sum(league["counts"]["teams"] for league in leagues),
            "matches": sum(league["counts"]["matches"] for league in leagues),
            "batters": sum(league["counts"]["batters"] for league in leagues),
            "pitchers": sum(league["counts"]["pitchers"] for league in leagues),
        },
        "leagues": leagues,
    }

    season_json_path = OUTPUT_DIR / f"season_{SEASON}.json"
    write_json(season_json_path, season_payload)

    site_json_path: Path | None = None
    if PUBLISH_TO_SITE_DATA:
        site_json_path = SITE_OUTPUT
        write_json(site_json_path, season_payload)

    report_json_path = OUTPUT_DIR / "fetch_report.json"
    report_text_path = OUTPUT_DIR / "fetch_report.txt"
    report = {
        "generated_at": generated_at,
        "season": SEASON,
        "selected_groups": selected_groups,
        "leagues": league_reports,
        "output_files": {
            "season_json": str(season_json_path.resolve()),
            "discovery_json": str(discovery_path.resolve()),
            "report_json": str(report_json_path.resolve()),
            "report_text": str(report_text_path.resolve()),
            "site_json": str(site_json_path.resolve()) if site_json_path else None,
        },
    }

    write_json(report_json_path, report)
    report_text_path.write_text(render_report(report), encoding="utf-8")

    print("[4/4] 저장 완료")
    print(f"      {season_json_path}")
    if site_json_path:
        print(f"      {site_json_path}")
    print(f"      {report_text_path}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build 2025 BSVBB full season data from probe-v2 discovery."
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="Actually fetch all teams/batting/pitching data. Without this flag only discovery is validated.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(fetch=args.fetch)
    except KeyboardInterrupt:
        print("\n사용자가 실행을 중단했습니다.")
        return 130
    except Exception as exc:
        print(f"\n오류: {type(exc).__name__}: {exc}")
        print("league_data_fetcher.py / landesliga_data_fetcher_vscode.py 및 probe-v2 discovery 파일을 확인하세요.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
