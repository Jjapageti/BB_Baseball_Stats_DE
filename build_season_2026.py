#!/usr/bin/env python3
"""2026 Verbandsliga/Landesliga JSON을 연도 통합 파일로 묶는다.

입력
----
- data/verbandsliga_2026.json
- data/landesliga_2026.json

출력
----
- data/seasons/2026.json

외부 패키지는 필요 없다.
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SEASON = 2026
TARGET_CLUB_ID = 492
TARGET_CLUB_NAME = "Berlin Sluggers"

REQUIRED_ARRAYS = ("teams", "matches", "standings", "batting", "pitching")

LEAGUE_SOURCES = (
    {
        "filename": "verbandsliga_2026.json",
        "key": "verbandsliga-regular-verbandsliga-baseball",
        "level": "verbandsliga",
        "stage": "regular",
    },
    {
        "filename": "landesliga_2026.json",
        "key": "landesliga-regular-landesliga-baseball",
        "level": "landesliga",
        "stage": "regular",
    },
)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"입력 파일이 없습니다: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 형식이 올바르지 않습니다: {path} ({exc})") from exc

    if not isinstance(data, dict):
        raise ValueError(f"JSON 최상단이 객체가 아닙니다: {path}")
    return data


def validate_combined(data: dict[str, Any], path: Path) -> None:
    league = data.get("league")
    if not isinstance(league, dict):
        raise ValueError(f"{path}: league 객체가 없습니다")

    source_season = league.get("season")
    if source_season is not None and int(source_season) != SEASON:
        raise ValueError(f"{path}: 시즌이 {SEASON}이 아닙니다 ({source_season})")

    for key in REQUIRED_ARRAYS:
        if not isinstance(data.get(key), list):
            raise ValueError(f"{path}: {key} 배열이 없습니다")


def list_or_empty(value: Any) -> list[Any]:
    return copy.deepcopy(value) if isinstance(value, list) else []


def add_player_context(
    rows: list[dict[str, Any]],
    *,
    key: str,
    name: str,
    level: str,
    stage: str,
) -> list[dict[str, Any]]:
    context = {
        "season": SEASON,
        "key": key,
        "name": name,
        "level": level,
        "stage": stage,
    }

    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cloned = copy.deepcopy(row)
        cloned["season"] = SEASON
        cloned["league_context"] = copy.deepcopy(context)
        result.append(cloned)
    return result


def normalize_source_groups(league: dict[str, Any]) -> list[dict[str, Any]]:
    raw_groups = league.get("source_groups")
    groups: list[dict[str, Any]] = []

    if isinstance(raw_groups, list):
        for group in raw_groups:
            if not isinstance(group, dict) or group.get("id") is None:
                continue
            groups.append(
                {
                    "id": group.get("id"),
                    "name": group.get("name"),
                    "acronym": group.get("acronym"),
                    **({"sport": group.get("sport")} if group.get("sport") else {}),
                }
            )

    if not groups and league.get("id") is not None:
        groups.append(
            {
                "id": league.get("id"),
                "name": league.get("name"),
                "acronym": league.get("acronym"),
            }
        )

    return groups


def build_league_payload(data: dict[str, Any], config: dict[str, str]) -> dict[str, Any]:
    source_league = data["league"]
    name = str(source_league.get("name") or config["level"].title())
    source_groups = normalize_source_groups(source_league)

    teams = list_or_empty(data.get("teams"))
    matches = list_or_empty(data.get("matches"))
    standings = list_or_empty(data.get("standings"))
    batting = add_player_context(
        list_or_empty(data.get("batting")),
        key=config["key"],
        name=name,
        level=config["level"],
        stage=config["stage"],
    )
    pitching = add_player_context(
        list_or_empty(data.get("pitching")),
        key=config["key"],
        name=name,
        level=config["level"],
        stage=config["stage"],
    )

    played_matches = sum(
        1
        for match in matches
        if isinstance(match, dict)
        and match.get("state") in {"played", "manually_valued"}
        and match.get("home_runs") is not None
        and match.get("away_runs") is not None
    )

    return {
        "key": config["key"],
        "name": name,
        "level": config["level"],
        "stage": config["stage"],
        "merged": bool(source_league.get("merged") or len(source_groups) > 1),
        "source_groups": source_groups,
        "season": SEASON,
        "counts": {
            "teams": len(teams),
            "matches": len(matches),
            "played_matches": played_matches,
            "batters": len(batting),
            "pitchers": len(pitching),
        },
        "teams": teams,
        "matches": matches,
        "standings": standings,
        "batting": batting,
        "pitching": pitching,
    }


def build_season_payload(root: Path) -> dict[str, Any]:
    data_dir = root / "data"
    leagues: list[dict[str, Any]] = []

    for config in LEAGUE_SOURCES:
        path = data_dir / config["filename"]
        data = read_json(path)
        validate_combined(data, path)
        leagues.append(build_league_payload(data, config))

    league_keys = [league["key"] for league in leagues]
    if len(league_keys) != len(set(league_keys)):
        raise ValueError("중복된 리그 key가 있습니다")

    return {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season": SEASON,
        "target_club": {
            "id": TARGET_CLUB_ID,
            "name": TARGET_CLUB_NAME,
        },
        "counts": {
            "leagues": len(leagues),
            "source_groups": sum(len(league["source_groups"]) for league in leagues),
            "teams": sum(league["counts"]["teams"] for league in leagues),
            "matches": sum(league["counts"]["matches"] for league in leagues),
            "batters": sum(league["counts"]["batters"] for league in leagues),
            "pitchers": sum(league["counts"]["pitchers"] for league in leagues),
        },
        "leagues": leagues,
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_season_file(root: Path | None = None) -> Path:
    project_root = Path(root) if root is not None else Path(__file__).resolve().parent
    output_path = project_root / "data" / "seasons" / f"{SEASON}.json"
    payload = build_season_payload(project_root)
    write_json(output_path, payload)
    return output_path


def main() -> int:
    try:
        print("[1/3] 2026 Verbandsliga/Landesliga 파일 확인")
        root = Path(__file__).resolve().parent
        for config in LEAGUE_SOURCES:
            print(f"      data/{config['filename']}")

        print("[2/3] 연도 통합 JSON 생성")
        output_path = build_season_file(root)
        payload = read_json(output_path)

        print("[3/3] 저장 완료")
        print(f"      {output_path.relative_to(root)}")
        print(
            "      "
            f"리그 {payload['counts']['leagues']} · "
            f"원본그룹 {payload['counts']['source_groups']} · "
            f"팀 {payload['counts']['teams']} · "
            f"경기 {payload['counts']['matches']} · "
            f"타자 {payload['counts']['batters']} · "
            f"투수 {payload['counts']['pitchers']}"
        )
        return 0
    except Exception as exc:
        print(f"\n오류: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
