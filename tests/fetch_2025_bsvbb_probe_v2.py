#!/usr/bin/env python3
"""
BSM / BSVBB 2025 discovery probe v2.

What changed from v1
--------------------
- No fuzzy/sub-string club-name matching.
- BSVBB seed clubs are matched by exact BSM club ID or exact acronym only.
- League candidates are deduplicated by league_id; league + second_league sources are merged.
- Known 2025 BSVBB local leagues are classified explicitly, so e.g. VLBBPO is not
  misclassified just because only one BSVBB club was seen in a seed match.
- Every unique match inside a candidate league is eligible for a direct
  /matches/<id>/match_boxscore.json request. statistics_published is recorded as
  metadata only and never used as a gate.
- Boxscore status is written for every candidate match.

The script intentionally keeps overregional candidates instead of deleting them.
Review the report before turning the candidates into a final allow-list.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://bsm.baseball-softball.de"
DEFAULT_SEASON = 2025
USER_AGENT = "BB-Baseball-Stats-DE/2025-discovery-v2 (+personal research project)"

# Exact BSM club IDs observed for the Berlin/Brandenburg clubs that seeded the
# 2025 discovery report. IDs are preferable because e.g. 'Ravensburg' must never
# accidentally match 'Ravens'. Acronyms are retained as an exact fallback.
BSVBB_CLUB_IDS = {
    485,  # Berlin Skylarks (BEA)
    486,  # SCC Challengers / SCC e.V. (BEC)
    491,  # NSF Berlin Ravens / Roosters (BER)
    492,  # Berlin Sluggers (BES)
    494,  # Berlin Wizards (BEW)
    495,  # Berlin Sliders (SLI)
    498,  # Potsdam Porcupines (POT)
    502,  # Berlin Ausbau Roadrunners (BWP)
    603,  # Mahlow Eagles (MEG)
    604,  # Berlin Flamingos (FLA)
}

BSVBB_CLUB_ACRONYMS = {
    "BEA", "BEC", "BER", "BES", "BEW", "SLI", "POT", "BWP", "MEG", "FLA",
}

# Explicit 2025 local BSVBB competition acronyms confirmed from the first report.
# Anything else discovered through a BSVBB club is preserved as overregional/review.
LOCAL_BSVBB_LEAGUE_ACRONYMS_BY_SEASON = {
    2023: {
        "BZLBB",       # Bezirksliga Baseball
        "JUGABB",      # Jugendaufbauliga Baseball
        "JUGBB",       # Jugendliga Baseball
        "JUNBB",       # Juniorenliga Baseball
        "JUNSB",       # Juniorinnenliga Softball
        "KINDBB",      # Kinderliga Baseball
        "LLBB",        # Landesliga Baseball
        "SCHBB",       # Schuelerliga Baseball
        "TOSSBB",      # Tossball Baseball
        "VLBB",        # Verbandsliga Baseball
        "VLSB",        # Verbandsliga Softball
    },
    2024: {
        "JUGABB",      # Jugendaufbauliga Baseball
        "JUGBB",       # Jugendliga Baseball
        "JUNBB",       # Juniorenliga Baseball
        "JUNSB",       # Juniorinnenliga Softball
        "LLBB",        # Landesliga Baseball
        "SCHBB",       # Schuelerliga Baseball
        "TOSSBB",      # Tossball Baseball
        "VLBB",        # Verbandsliga Baseball
        "VLSB",        # Verbandsliga Softball
    },
    2025: {
        "COPI",        # Coach Pitch
        "JUGA",        # Jugendaufbauliga Baseball
        "JUGBB",       # Jugendliga Baseball
        "JUNBB",       # Juniorenliga Baseball
        "JUNSB",       # Juniorinnenliga Softball
        "LLBBDIVA",    # Landesliga Baseball Division A
        "LLBBDIVB",    # Landesliga Baseball Division B
        "LLBBPO",      # Landesliga postseason / PO
        "SCHBB",       # Schuelerliga Baseball
        "VLBB",        # Verbandsliga Baseball
        "VLBBPO",      # Verbandsliga postseason / PO
        "VLSB",        # Verbandsliga Softball
    },
}

# Backward-compatible alias for older imports/tests.
LOCAL_BSVBB_LEAGUE_ACRONYMS_2025 = (
    LOCAL_BSVBB_LEAGUE_ACRONYMS_BY_SEASON[2025]
)

FetchJson = Callable[[str], Any]


def normalize_acronym(value: Any) -> str:
    return str(value or "").strip().upper()


def http_get_json(url: str, *, timeout: int = 45, retries: int = 2) -> Any:
    """GET JSON with small retry handling for transient network/server failures."""
    last_error: BaseException | None = None
    for attempt in range(retries + 1):
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                payload = response.read().decode(charset)
            return json.loads(payload)
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt >= retries:
                raise
        except (URLError, TimeoutError) as exc:
            last_error = exc
            if attempt >= retries:
                raise
        if attempt < retries:
            time.sleep(0.6 * (attempt + 1))
    if last_error:
        raise last_error
    raise RuntimeError("Unexpected HTTP retry state")


def build_matches_url(season: int) -> str:
    params = [
        ("compact", "true"),
        ("show_all", "true"),
        ("filters[seasons][]", str(season)),
        ("filters[gamedays][]", "any"),
    ]
    return f"{BASE_URL}/matches.json?{urlencode(params)}"


def team_from_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {}
    team = entry.get("team")
    return team if isinstance(team, dict) else {}


def is_bsvbb_club(club: dict[str, Any]) -> bool:
    """Exact membership test only: club ID first, exact acronym second."""
    club_id = club.get("id")
    try:
        if club_id is not None and int(club_id) in BSVBB_CLUB_IDS:
            return True
    except (TypeError, ValueError):
        pass
    return normalize_acronym(club.get("acronym")) in BSVBB_CLUB_ACRONYMS


def match_bsvbb_clubs(match: dict[str, Any]) -> list[dict[str, Any]]:
    """Return distinct exact-matched BSVBB club objects from the two lineup entries."""
    found: dict[str, dict[str, Any]] = {}
    for side in ("home_league_entry", "away_league_entry"):
        team = team_from_entry(match.get(side))
        for club in team.get("clubs") or []:
            if not isinstance(club, dict) or not is_bsvbb_club(club):
                continue
            key = f"id:{club.get('id')}" if club.get("id") is not None else f"acr:{normalize_acronym(club.get('acronym'))}"
            found[key] = {
                "id": club.get("id"),
                "name": club.get("name"),
                "acronym": club.get("acronym"),
                "short_name": club.get("short_name"),
            }
    return sorted(found.values(), key=lambda c: (normalize_acronym(c.get("acronym")), int(c.get("id") or 0)))


def iter_match_leagues(match: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    for source in ("league", "second_league"):
        league = match.get(source)
        if isinstance(league, dict) and league.get("id") is not None:
            yield source, league


def classify_scope(
    league: dict[str, Any],
    season: int = DEFAULT_SEASON,
) -> str:
    acronym = normalize_acronym(league.get("acronym"))
    local_acronyms = LOCAL_BSVBB_LEAGUE_ACRONYMS_BY_SEASON.get(
        int(season),
        set(),
    )
    if acronym in local_acronyms:
        return "local_bsvbb"
    return "overregional_candidate"


def build_candidate_leagues(
    matches: list[dict[str, Any]],
    *,
    season: int = DEFAULT_SEASON,
) -> list[dict[str, Any]]:
    """
    Discover a league when at least one exact BSVBB club appears in one of its matches.

    The unique key is league_id only. If the same league is seen in both `league` and
    `second_league`, both source labels are retained in `league_sources`.
    """
    buckets: dict[int, dict[str, Any]] = {}

    for match in matches:
        bsvbb_clubs = match_bsvbb_clubs(match)
        if not bsvbb_clubs:
            continue

        for source, league in iter_match_leagues(match):
            league_id = int(league["id"])
            bucket = buckets.setdefault(
                league_id,
                {
                    "league_id": league_id,
                    "league_name": league.get("name"),
                    "league_acronym": league.get("acronym"),
                    "sport": league.get("sport"),
                    "human_sport": league.get("human_sport"),
                    "league_sources": set(),
                    "seed_match_ids": set(),
                    "bsvbb_clubs": {},
                },
            )
            bucket["league_sources"].add(source)
            if match.get("id") is not None:
                bucket["seed_match_ids"].add(int(match["id"]))
            for club in bsvbb_clubs:
                key = f"id:{club.get('id')}" if club.get("id") is not None else f"acr:{normalize_acronym(club.get('acronym'))}"
                bucket["bsvbb_clubs"][key] = club

    # Count all unique matches in each discovered league, not only the seed matches.
    all_match_ids_by_league: dict[int, set[int]] = defaultdict(set)
    for match in matches:
        if match.get("id") is None:
            continue
        mid = int(match["id"])
        for _, league in iter_match_leagues(match):
            lid = int(league["id"])
            if lid in buckets:
                all_match_ids_by_league[lid].add(mid)

    result: list[dict[str, Any]] = []
    for league_id, bucket in buckets.items():
        league_stub = {"acronym": bucket.get("league_acronym")}
        result.append(
            {
                "league_id": league_id,
                "league_name": bucket.get("league_name"),
                "league_acronym": bucket.get("league_acronym"),
                "sport": bucket.get("sport"),
                "human_sport": bucket.get("human_sport"),
                "scope": classify_scope(
                    league_stub,
                    season=season,
                ),
                "league_sources": sorted(bucket["league_sources"]),
                "seed_match_count": len(bucket["seed_match_ids"]),
                "total_match_count": len(all_match_ids_by_league.get(league_id, set())),
                "bsvbb_club_count": len(bucket["bsvbb_clubs"]),
                "bsvbb_clubs": sorted(
                    bucket["bsvbb_clubs"].values(),
                    key=lambda c: (normalize_acronym(c.get("acronym")), int(c.get("id") or 0)),
                ),
            }
        )

    return sorted(
        result,
        key=lambda row: (
            0 if row["scope"] == "local_bsvbb" else 1,
            normalize_acronym(row.get("league_acronym")),
            int(row["league_id"]),
        ),
    )


def select_candidate_matches(matches: list[dict[str, Any]], candidate_league_ids: set[int]) -> list[dict[str, Any]]:
    """Select every match in a discovered league and deduplicate by the BSM match PK."""
    selected: dict[int, dict[str, Any]] = {}
    for match in matches:
        match_id = match.get("id")
        if match_id is None:
            continue
        league_ids = {int(league["id"]) for _, league in iter_match_leagues(match)}
        if league_ids & candidate_league_ids:
            selected[int(match_id)] = match
    return [selected[mid] for mid in sorted(selected)]


def candidate_relations(match: dict[str, Any], candidate_league_ids: set[int]) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for source, league in iter_match_leagues(match):
        league_id = int(league["id"])
        if league_id not in candidate_league_ids:
            continue
        key = (source, league_id)
        if key in seen:
            continue
        seen.add(key)
        relations.append(
            {
                "source": source,
                "league_id": league_id,
                "league_acronym": league.get("acronym"),
                "league_name": league.get("name"),
            }
        )
    return relations


def compact_match_record(match: dict[str, Any], candidate_league_ids: set[int] | None = None) -> dict[str, Any]:
    candidate_league_ids = candidate_league_ids or set()
    return {
        "id": match.get("id"),
        "match_id": match.get("match_id"),
        "time": match.get("time"),
        "state": match.get("state"),
        "human_state": match.get("human_state"),
        "home_team": match.get("home_team_name"),
        "away_team": match.get("away_team_name"),
        "home_runs": match.get("home_runs"),
        "away_runs": match.get("away_runs"),
        "statistics_published_flag": match.get("statistics_published"),
        "candidate_leagues": candidate_relations(match, candidate_league_ids),
        "bsvbb_clubs_in_match": match_bsvbb_clubs(match),
    }


def boxscore_url(match_pk: Any) -> str:
    return f"{BASE_URL}/matches/{match_pk}/match_boxscore.json"


def probe_one_boxscore(match: dict[str, Any], *, fetch_json: FetchJson = http_get_json) -> dict[str, Any]:
    """Directly request one Boxscore regardless of the compact statistics_published flag."""
    match_pk = match.get("id")
    result = compact_match_record(match)
    result["boxscore_url"] = boxscore_url(match_pk)

    if match_pk is None:
        result["boxscore_status"] = "missing_match_id"
        return result

    try:
        data = fetch_json(result["boxscore_url"])
        if data in (None, {}, []):
            result["boxscore_status"] = "empty"
        else:
            result["boxscore_status"] = "available"
            result["_boxscore_data"] = data
    except HTTPError as exc:
        result["boxscore_status"] = f"http_{exc.code}"
        result["boxscore_error"] = str(exc)
    except (URLError, TimeoutError) as exc:
        result["boxscore_status"] = "network_error"
        result["boxscore_error"] = str(exc)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        result["boxscore_status"] = "invalid_json"
        result["boxscore_error"] = str(exc)
    except Exception as exc:  # keep one bad match from terminating the whole season probe
        result["boxscore_status"] = "unexpected_error"
        result["boxscore_error"] = f"{type(exc).__name__}: {exc}"
    return result


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def probe_boxscores(
    matches: list[dict[str, Any]],
    boxscore_dir: Path,
    candidate_league_ids: set[int],
    *,
    delay: float = 0.15,
) -> list[dict[str, Any]]:
    boxscore_dir.mkdir(parents=True, exist_ok=True)
    statuses: list[dict[str, Any]] = []
    total = len(matches)

    for index, match in enumerate(matches, start=1):
        match_pk = match.get("id")
        print(f"  Boxscore [{index}/{total}] match {match_pk} ...", end=" ", flush=True)
        row = probe_one_boxscore(match)
        data = row.pop("_boxscore_data", None)
        # Rebuild candidate relations because probe_one_boxscore deliberately has no discovery context.
        row["candidate_leagues"] = candidate_relations(match, candidate_league_ids)

        if row["boxscore_status"] == "available" and data not in (None, {}, []):
            save_json(boxscore_dir / f"{match_pk}.json", data)
            print("OK")
        else:
            print(row["boxscore_status"].upper())
        statuses.append(row)

        if delay > 0 and index < total:
            time.sleep(delay)

    return statuses


def make_unprobed_statuses(matches: list[dict[str, Any]], candidate_league_ids: set[int]) -> list[dict[str, Any]]:
    rows = []
    for match in matches:
        row = compact_match_record(match, candidate_league_ids)
        row["boxscore_url"] = boxscore_url(match.get("id"))
        row["boxscore_status"] = "not_probed"
        rows.append(row)
    return rows


def make_report(
    season: int,
    all_matches: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    candidate_matches: list[dict[str, Any]],
    statuses: list[dict[str, Any]],
) -> str:
    counts: dict[str, int] = defaultdict(int)
    published_flags: dict[str, int] = defaultdict(int)
    for row in statuses:
        counts[str(row.get("boxscore_status") or "unknown")] += 1
        flag = row.get("statistics_published_flag")
        published_flags[str(flag).lower()] += 1

    local = [row for row in candidates if row["scope"] == "local_bsvbb"]
    overregional = [row for row in candidates if row["scope"] != "local_bsvbb"]

    lines = [
        f"===== BSM / BSVBB discovery v2 {season} =====",
        "",
        f"All BSM matches downloaded: {len(all_matches)}",
        f"Unique candidate leagues: {len(candidates)}",
        f"  local_bsvbb: {len(local)}",
        f"  overregional_candidate: {len(overregional)}",
        f"Unique matches inside candidate leagues: {len(candidate_matches)}",
        "",
        f"--- Local BSVBB leagues (explicit {season} classification) ---",
    ]

    def append_league(row: dict[str, Any]) -> None:
        sources = ",".join(row.get("league_sources") or [])
        lines.append(
            f"[{row['scope']}] {str(row.get('league_acronym') or '-'):<12} "
            f"id={row.get('league_id')}  {row.get('league_name') or '-'}  "
            f"sport={row.get('human_sport') or row.get('sport') or '-'}  "
            f"sources={sources or '-'}  seeds={row.get('seed_match_count')}  "
            f"all_matches={row.get('total_match_count')}"
        )
        clubs = [
            f"{c.get('acronym') or '?'}:{c.get('short_name') or c.get('name') or c.get('id')}"
            for c in row.get("bsvbb_clubs") or []
        ]
        if clubs:
            lines.append("    -> " + ", ".join(clubs))

    for row in local:
        append_league(row)

    lines.extend(["", "--- Overregional / review candidates ---"])
    for row in overregional:
        append_league(row)

    lines.extend(["", "--- Compact statistics_published flag (metadata only) ---"])
    for key in sorted(published_flags):
        lines.append(f"{key}: {published_flags[key]}")

    lines.extend(["", "--- Direct Boxscore probe status ---"])
    for key in sorted(counts):
        lines.append(f"{key}: {counts[key]}")

    probed_total = sum(value for key, value in counts.items() if key != "not_probed")
    available = counts.get("available", 0)
    coverage = (available / probed_total * 100.0) if probed_total else 0.0
    lines.append(f"Direct public Boxscore coverage: {available}/{probed_total} ({coverage:.1f}%)")
    lines.append("")
    lines.append("Important: statistics_published from compact matches is NOT used to decide whether a Boxscore URL is requested.")
    lines.append("Review overregional_candidate before using it as a final season allow-list.")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover 2025 BSVBB-related BSM leagues and directly probe public Boxscores.")
    parser.add_argument("--season", type=int, default=DEFAULT_SEASON)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: bsm_season_data/<season>_discovery_v2)",
    )
    parser.add_argument(
        "--raw-file",
        type=Path,
        default=None,
        help="Optional existing compact matches JSON. If provided, BSM matches are not re-downloaded.",
    )
    parser.add_argument(
        "--no-boxscores",
        action="store_true",
        help="Discover/dedupe leagues and matches but do not request Boxscore URLs.",
    )
    parser.add_argument("--delay", type=float, default=0.15, help="Delay between Boxscore requests in seconds.")
    return parser.parse_args(argv)


def load_matches(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.raw_file:
        print(f"[1/4] Loading existing raw matches: {args.raw_file}")
        data = json.loads(args.raw_file.read_text(encoding="utf-8"))
    else:
        url = build_matches_url(args.season)
        print(f"[1/4] Downloading BSM matches for {args.season}")
        print(f"      {url}")
        data = http_get_json(url)
    if not isinstance(data, list):
        raise TypeError(f"Expected a JSON list, got {type(data).__name__}")
    return data


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = args.output or Path("bsm_season_data") / f"{args.season}_discovery_v2"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        matches = load_matches(args)
    except Exception as exc:
        print(f"ERROR: could not load matches: {exc}", file=sys.stderr)
        return 1

    save_json(out_dir / "raw_matches.json", matches)
    print(f"      {len(matches)} matches loaded")

    print("[2/4] Discovering and deduplicating candidate leagues")
    candidates = build_candidate_leagues(
        matches,
        season=args.season,
    )
    save_json(out_dir / "candidate_leagues.json", candidates)
    candidate_ids = {int(row["league_id"]) for row in candidates}
    candidate_matches = select_candidate_matches(matches, candidate_ids)
    save_json(
        out_dir / "candidate_matches.json",
        [compact_match_record(match, candidate_ids) for match in candidate_matches],
    )
    print(f"      {len(candidates)} unique candidate leagues / {len(candidate_matches)} unique matches")

    print("[3/4] Boxscore step")
    if args.no_boxscores:
        statuses = make_unprobed_statuses(candidate_matches, candidate_ids)
        print("      skipped (--no-boxscores)")
    else:
        statuses = probe_boxscores(
            candidate_matches,
            out_dir / "boxscores",
            candidate_ids,
            delay=max(args.delay, 0.0),
        )
    save_json(out_dir / "boxscore_status.json", statuses)

    print("[4/4] Writing report")
    report = make_report(args.season, matches, candidates, candidate_matches, statuses)
    (out_dir / "report.txt").write_text(report, encoding="utf-8")
    print(report)
    print(f"Saved to: {out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
