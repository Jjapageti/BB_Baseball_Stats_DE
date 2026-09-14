from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SEASON = 2026
SCOREKEEPER_ROOT = ROOT.parent / "BB_Scorekeeper_DBV_v6_1"
SOURCES = (
    ROOT / "bsm_league_data" / "verbandsliga_2026" / "combined.json",
    ROOT / "bsm_league_data" / "landesliga_2026" / "combined.json",
)


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        value = json.load(file)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def person_name(person: Any) -> str:
    if not isinstance(person, dict):
        return ""
    name = str(person.get("name") or "").strip()
    if name:
        return name
    parts = [person.get("first_name"), person.get("last_name")]
    return " ".join(str(part).strip() for part in parts if str(part or "").strip())


def team_info(row: Any) -> tuple[str, str]:
    if not isinstance(row, dict):
        return "", ""
    entry = row.get("league_entry")
    if not isinstance(entry, dict):
        return "", ""
    team_id = str(entry.get("id") or "").strip()
    name = str(entry.get("name") or "").strip()
    return team_id, name


def team_logo(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    candidates = [row.get("club"), (row.get("league_entry") or {}).get("club") if isinstance(row.get("league_entry"), dict) else None]
    for club in candidates:
        if isinstance(club, dict):
            logo = str(club.get("logo_url") or "").strip()
            if logo:
                return logo
    clubs = row.get("clubs")
    if isinstance(clubs, list):
        for club in clubs:
            if isinstance(club, dict) and club.get("logo_url"):
                return str(club["logo_url"]).strip()
    return ""


def add_player(teams: dict[str, dict[str, Any]], row: Any, league_name: str) -> None:
    if not isinstance(row, dict):
        return
    team_id, team_name = team_info(row)
    player = row.get("person")
    name = person_name(player)
    if not team_id or not team_name or not name:
        return
    team = teams.setdefault(
        team_id,
        {"id": team_id, "name": team_name, "league": league_name, "logo_url": team_logo(row), "players": {}},
    )
    if not team.get("logo_url"):
        team["logo_url"] = team_logo(row)
    player_id = str(player.get("id") or name) if isinstance(player, dict) else name
    team["players"].setdefault(player_id, {"id": player_id, "name": name})


def build_roster() -> dict[str, Any]:
    teams: dict[str, dict[str, Any]] = {}
    source_files: list[str] = []
    for source in SOURCES:
        if not source.exists():
            continue
        data = read_json(source)
        league = data.get("league") if isinstance(data.get("league"), dict) else {}
        league_name = str(league.get("name") or source.parent.name)
        source_files.append(str(source))
        for key in ("batting", "pitching"):
            for row in data.get(key, []):
                add_player(teams, row, league_name)

    output_teams = []
    for team in sorted(teams.values(), key=lambda item: item["name"].casefold()):
        players = sorted(team.pop("players").values(), key=lambda item: item["name"].casefold())
        output_teams.append({**team, "players": players})
    return {
        "schema_version": 1,
        "season": SEASON,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_files": source_files,
        "teams": output_teams,
    }


def generate(output: Path | None = None) -> Path:
    target = output or SCOREKEEPER_ROOT / "data" / f"rosters-{SEASON}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build_roster(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    target = generate()
    payload = json.loads(target.read_text(encoding="utf-8"))
    print(f"[OK] Scorekeeper roster written: {target.name}")
    print(f"  Teams {len(payload['teams'])} · Players {sum(len(team['players']) for team in payload['teams'])}")
