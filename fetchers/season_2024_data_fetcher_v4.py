#!/usr/bin/env python3
"""BSM에서 Berlin Sluggers가 참가한 2024 성인 야구 리그 전체 데이터를 수집한다.

VS Code에서 이 파일을 열고 ``Run Python File`` 버튼으로 실행하면 된다.
명령행 인자와 외부 Python 패키지는 필요 없다.

필수 파일
---------
이 파일과 같은 폴더에 아래 두 파일이 있어야 한다.

- league_data_fetcher.py
- landesliga_data_fetcher_vscode.py

동작
----
1. 2023 시즌 전체 경기 목록을 내려받는다.
2. Club ID 492(Berlin Sluggers)가 참가한 성인 남자 야구 리그를 찾는다.
3. Berlin Sluggers 경기의 league/second_league로 직접 연결된 그룹만 병합한다.
4. 각 리그의 전체 팀, 경기, 순위, 타자, 투수 기록을 수집한다.
5. 모든 리그를 연도별 JSON 하나로 저장한다.

주요 출력
---------
- bsm_season_data/2023/season_2023.json
- data/seasons/2023.json                 (웹사이트용 복사본)
- bsm_season_data/2023/fetch_report.txt
- bsm_season_data/2023/discovery.json
"""

from __future__ import annotations

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
SEASON = 2024
SCRIPT_VERSION = "2026-08-05-region-fix-v4"
TARGET_CLUB_ID = 492
TARGET_CLUB_NAME = "Berlin Sluggers"

# True이면 Playoffs/Playdowns/Relegation 등도 별도 리그로 저장한다.
INCLUDE_POSTSEASON = True

# True이면 전체 수집 결과를 웹사이트용 data/seasons/2023.json에도 복사한다.
PUBLISH_TO_SITE_DATA = True

OUTPUT_ROOT = Path("bsm_season_data")
OUTPUT_DIR = OUTPUT_ROOT / str(SEASON)
SITE_OUTPUT = Path("data") / "seasons" / f"{SEASON}.json"

TIMEOUT = 35.0
RETRIES = 3
REQUEST_DELAY = 0.15

# 성인 남자 야구 리그로 인정할 명칭.
ADULT_LEVEL_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("1-bundesliga", ("1. baseball-bundesliga", "1. bundesliga")),
    ("2-bundesliga", ("2. baseball-bundesliga", "2. bundesliga")),
    ("bundesliga", ("bundesliga",)),
    ("regionalliga", ("regionalliga",)),
    ("verbandsliga", ("verbandsliga",)),
    ("landesliga", ("landesliga",)),
    ("bezirksliga", ("bezirksliga", "vezirksliga")),
)

YOUTH_TERMS = (
    "schüler",
    "schueler",
    "jugend",
    "junioren",
    "juniorinnen",
    "nachwuchs",
    "u8",
    "u9",
    "u10",
    "u11",
    "u12",
    "u13",
    "u14",
    "u15",
    "u16",
    "u18",
    "coach pitch",
    "coach-pitch",
    "t-ball",
    "tee-ball",
    "winterliga",
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
    "1-bundesliga": 10,
    "2-bundesliga": 20,
    "bundesliga": 25,
    "regionalliga": 30,
    "verbandsliga": 40,
    "landesliga": 50,
    "bezirksliga": 60,
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
# 리그 분류
# ---------------------------------------------------------------------------
def league_search_text(group: dict[str, Any]) -> str:
    return " ".join(
        [text(group.get("name")), text(group.get("acronym")), text(group.get("human_sport"))]
    ).casefold()


def classify_level(group: dict[str, Any]) -> str | None:
    haystack = league_search_text(group)
    for level, patterns in ADULT_LEVEL_PATTERNS:
        if any(pattern in haystack for pattern in patterns):
            return level
    return None


def classify_stage(group: dict[str, Any]) -> str:
    haystack = league_search_text(group)
    compact = re.sub(r"[^a-z0-9]", "", haystack)
    acronym = re.sub(r"[^a-z0-9]", "", text(group.get("acronym")).casefold())

    # BSM은 이름/약어에 Play-downs를 여러 형태로 표기한다.
    postseason = any(term.replace("-", "") in compact for term in POSTSEASON_TERMS)
    acronym_postseason = bool(
        re.search(r"(?:po|pof|playoff|pd|playdown|rel|relegation)$", acronym)
    )
    return "postseason" if postseason or acronym_postseason else "regular"


def is_adult_baseball_group(group: dict[str, Any]) -> bool:
    sport = text(group.get("sport")).casefold()
    haystack = league_search_text(group)

    # sport 필드가 존재하면 남자 야구만 허용한다.
    if sport and sport != "baseball_male":
        return False
    if any(term in haystack for term in YOUTH_TERMS):
        return False
    if classify_level(group) is None:
        return False
    if not INCLUDE_POSTSEASON and classify_stage(group) == "postseason":
        return False
    return True


def normalize_family_name(name: Any) -> str:
    value = text(name).casefold()
    value = (
        value.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )

    # DivA, Division B, Gruppe 1 같은 그룹 꼬리표만 제거한다.
    value = re.sub(r"\b(?:division|div\.?|gruppe|group)\s*[-:]?\s*[a-z0-9]+\b", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" -_/()")
    return value


def group_family_key(group: dict[str, Any]) -> tuple[Any, ...]:
    federation_ids = tuple(sorted(group.get("federation_ids", []) or []))
    level = classify_level(group) or "unknown"
    stage = classify_stage(group)
    family_name = normalize_family_name(group.get("name"))

    # 명칭이 비어 있으면 acronym에서 DivA/DivB 꼬리표를 제거한다.
    if not family_name:
        family_name = re.sub(
            r"(?:div|gruppe|group)[a-z0-9]+$",
            "",
            text(group.get("acronym")).casefold(),
        )
    return federation_ids, level, stage, family_name


def merge_group_catalog(matches: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """시즌 전체 경기에서 리그 카탈로그와 Sluggers 직접 연결만 만든다."""
    catalog: dict[int, dict[str, Any]] = {}

    for match in matches:
        federation_id = federation_id_from_match(match)
        target_match = match_contains_target_club(match)
        entities = [
            entity
            for entity in league_objects_from_match(match)
            if is_adult_baseball_group(entity)
        ]
        group_ids = unique_sorted(as_int(entity.get("id")) for entity in entities)
        match_id = as_int(match.get("id"))

        for entity in entities:
            group_id = as_int(entity.get("id"))
            if group_id is None:
                continue

            current = catalog.setdefault(
                group_id,
                {
                    "id": group_id,
                    "name": nonempty(entity.get("name")),
                    "acronym": nonempty(entity.get("acronym")),
                    "sport": nonempty(entity.get("sport")),
                    "human_sport": nonempty(entity.get("human_sport")),
                    "level": classify_level(entity),
                    "stage": classify_stage(entity),
                    "match_count": 0,
                    "target_match_count": 0,
                    "target_match_ids": [],
                    "federation_ids": [],
                    "source_fields": [],
                    "target_source_fields": [],
                    "linked_group_ids": [],
                },
            )
            current["match_count"] += 1
            source_field = entity.get("source_field")
            if target_match:
                current["target_match_count"] += 1
                if match_id is not None and match_id not in current["target_match_ids"]:
                    current["target_match_ids"].append(match_id)
                if source_field and source_field not in current["target_source_fields"]:
                    current["target_source_fields"].append(source_field)

                # 오직 Sluggers가 실제 참가한 경기의 league/second_league 연결만 병합한다.
                for linked_id in group_ids:
                    if linked_id != group_id and linked_id not in current["linked_group_ids"]:
                        current["linked_group_ids"].append(linked_id)

            if federation_id is not None and federation_id not in current["federation_ids"]:
                current["federation_ids"].append(federation_id)
            if source_field and source_field not in current["source_fields"]:
                current["source_fields"].append(source_field)

            for key in ("name", "acronym", "sport", "human_sport"):
                if not current.get(key) and entity.get(key):
                    current[key] = entity.get(key)

    rows = list(catalog.values())
    for row in rows:
        row["federation_ids"] = unique_sorted(row.get("federation_ids", []))
        row["linked_group_ids"] = unique_sorted(row.get("linked_group_ids", []))
        row["target_match_ids"] = unique_sorted(row.get("target_match_ids", []))
        row["target_source_fields"] = sorted(set(row.get("target_source_fields", [])))
        row["family_key"] = list(group_family_key(row))
    return sorted(
        rows,
        key=lambda row: (LEVEL_ORDER.get(row["level"], 999), row["stage"], row["id"]),
    )


def select_target_groups(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Berlin Sluggers가 직접 참가한 경기에서 확인된 그룹만 선택한다.

    같은 이름, 같은 레벨, 같은 연맹이라는 이유로 타 지역 그룹을 추가하지 않는다.
    target 경기의 second_league도 자체 target_match_count가 증가하므로 자동 포함된다.
    """
    return [row for row in catalog if row.get("target_match_count", 0) > 0]


def build_logical_leagues(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sluggers 경기에서 확인된 명시적 연결의 connected component별로 묶는다."""
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
        level = source_groups[0].get("level") or "unknown"
        stage = source_groups[0].get("stage") or "regular"
        names = [text(row.get("name")) for row in source_groups if text(row.get("name"))]
        display_name = Counter(names).most_common(1)[0][0] if names else level.title()
        base_key = safe_slug(f"{level}-{stage}-{display_name}")
        used_keys[base_key] += 1
        key = base_key if used_keys[base_key] == 1 else f"{base_key}-{used_keys[base_key]}"

        logical.append(
            {
                "key": key,
                "name": display_name,
                "level": level,
                "stage": stage,
                "merged": len(source_groups) > 1,
                "source_groups": [
                    {
                        "id": row["id"],
                        "name": row.get("name"),
                        "acronym": row.get("acronym"),
                        "sport": row.get("sport"),
                        "federation_ids": row.get("federation_ids", []),
                        "match_count": row.get("match_count", 0),
                        "target_match_count": row.get("target_match_count", 0),
                        "target_match_ids": row.get("target_match_ids", []),
                        "target_source_fields": row.get("target_source_fields", []),
                        "linked_group_ids": row.get("linked_group_ids", []),
                    }
                    for row in source_groups
                ],
            }
        )

    return sorted(
        logical,
        key=lambda row: (
            LEVEL_ORDER.get(row["level"], 999),
            1 if row["stage"] == "postseason" else 0,
            row["name"].casefold(),
            row["key"],
        ),
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
            for key in ("key", "name", "level", "stage", "merged", "source_groups", "counts")
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
        f"BSM SEASON {SEASON} ADULT BASEBALL FETCH REPORT",
        "=" * 82,
        f"Erstellt          : {report['generated_at']}",
        f"Saison            : {report['season']}",
        f"Zielverein        : {report['target_club']['name']} (Club-ID {report['target_club']['id']})",
        f"Saisonspiele      : {report['season_match_count']}",
        f"Erkannte Ligen    : {len(report['selected_groups'])} Quellgruppen",
        f"Gespeicherte Ligen: {len(report['leagues'])}",
        "",
        "[AUSGEWÄHLTE QUELLGRUPPEN]",
    ]

    for group in report["selected_groups"]:
        lines.append(
            f"- {group.get('acronym') or '-':<16} id={group['id']:<6} "
            f"level={group.get('level'):<15} stage={group.get('stage'):<10} "
            f"matches={group.get('match_count', 0):<4} "
            f"Sluggers-Matches={group.get('target_match_count', 0):<3} "
            f"name={group.get('name')}"
        )

    lines.extend(["", "[GESPEICHERTE LIGEN]"])
    for league in report["leagues"]:
        meta = league["league"]
        counts = meta["counts"]
        source_ids = ", ".join(str(g["id"]) for g in meta["source_groups"])
        lines.append(
            f"- {meta['name']} | key={meta['key']} | source={source_ids} | "
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
            f"season_{SEASON}.json enthält alle erkannten Erwachsenenligen der Berlin Sluggers.",
        ]
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
def run() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[Fetcher-Version] {SCRIPT_VERSION}")
    print("[Region-Filter] strict club.id=492 / league+second_league only / no name fallback")
    print(f"[1/4] {SEASON} 시즌 전체 경기 목록 조회")
    matches_url = build_season_matches_url()
    print(f"      {matches_url}")
    response = fetch_json(matches_url, timeout=TIMEOUT, retries=RETRIES)
    if not response.get("ok"):
        raise RuntimeError(f"경기 목록 조회 실패: {response.get('error')}")

    season_matches = iter_matches(response.get("payload"))
    if not season_matches:
        raise RuntimeError(f"{SEASON} 시즌 경기 응답에서 경기 행을 찾지 못했습니다.")

    raw_matches_path = OUTPUT_DIR / "raw" / "season_matches.json"
    write_json(raw_matches_path, season_matches)
    print(f"      경기 {len(season_matches)}개")

    print("[2/4] Sluggers 성인 리그 탐색")
    catalog = merge_group_catalog(season_matches)
    selected_groups = select_target_groups(catalog)
    logical_leagues = build_logical_leagues(selected_groups)

    discovery_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season": SEASON,
        "source_url": matches_url,
        "target_club": {"id": TARGET_CLUB_ID, "name": TARGET_CLUB_NAME},
        "all_adult_groups": catalog,
        "selected_groups": selected_groups,
        "logical_leagues": logical_leagues,
    }
    discovery_path = OUTPUT_DIR / "discovery.json"
    write_json(discovery_path, discovery_payload)

    if not selected_groups:
        print(f"      Sluggers가 참가한 {SEASON} 성인리그를 찾지 못했습니다.")
        print(f"      진단 파일: {discovery_path}")
        return 2

    for group in selected_groups:
        print(
            f"      - {group.get('acronym') or '-'} id={group['id']} "
            f"| {group.get('name')} | {group.get('stage')} "
            f"| Sluggers-Spiele={group.get('target_match_count', 0)} "
            f"| Quelle={'+'.join(group.get('target_source_fields', [])) or '-'}"
        )

    print(f"[3/4] 전체 리그 데이터 수집 ({len(logical_leagues)}개)")
    leagues: list[dict[str, Any]] = []
    league_reports: list[dict[str, Any]] = []
    for index, logical in enumerate(logical_leagues, start=1):
        payload, league_report = fetch_logical_league(logical, index, len(logical_leagues))
        leagues.append(payload)
        league_reports.append(league_report)

    generated_at = datetime.now(timezone.utc).isoformat()
    season_payload = {
        "schema_version": 2,
        "generated_at": generated_at,
        "season": SEASON,
        "target_club": {"id": TARGET_CLUB_ID, "name": TARGET_CLUB_NAME},
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
        "target_club": season_payload["target_club"],
        "season_match_count": len(season_matches),
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


def main() -> int:
    try:
        return run()
    except KeyboardInterrupt:
        print("\n사용자가 실행을 중단했습니다.")
        return 130
    except Exception as exc:
        print(f"\n오류: {type(exc).__name__}: {exc}")
        print("league_data_fetcher.py와 landesliga_data_fetcher_vscode.py가 같은 폴더에 있는지 확인하세요.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
