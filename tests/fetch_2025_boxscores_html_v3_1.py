#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BSM 2025 Boxscore HTML fetcher/parser v3

배경
----
BSM 문서에는 match_boxscore.json이 공개 API로 안내되어 있지만,
실제 환경에서 JSON 경로가 nginx 403을 반환하는 경우가 확인되었다.
반면 사람이 보는 HTML Boxscore 페이지는 200으로 열리므로,
이 스크립트는 HTML 페이지를 공식 공개 화면에서 받아 구조화된 JSON으로 저장한다.

의존성
------
requests 만 사용. BeautifulSoup/pandas 불필요.

주요 사용법
-----------
1) 한 경기만 네트워크로 테스트:
   python fetch_2025_boxscores_html_v3.py --match-id 59028

2) 이미 저장된 HTML 파일만 오프라인 파싱:
   python fetch_2025_boxscores_html_v3.py --html-file bsm_boxscore_debug/59028/03_html_browser_headers.html

3) 2025 후보 경기 전체 처리:
   python fetch_2025_boxscores_html_v3.py

기본 candidate_matches.json 탐색 위치:
- tests/bsm_season_data/2025_discovery_v2/candidate_matches.json
- bsm_season_data/2025_discovery_v2/candidate_matches.json

기본적으로 statistics_published_flag=true 경기만 요청한다.
--probe-all 을 주면 false 경기까지 요청한다.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests


BASE_URL = "https://bsm.baseball-softball.de"
TIMEOUT = 25
DEFAULT_DELAY = 0.35

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Upgrade-Insecure-Requests": "1",
}


def normalize_text(value: str) -> str:
    value = html.unescape(value or "")
    value = value.replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


class TableData:
    def __init__(self) -> None:
        self.rows: list[list[str]] = []


class SimpleTableParser(HTMLParser):
    """필요한 수준으로 BSM HTML의 title과 table cell 텍스트만 추출."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[TableData] = []
        self.title_parts: list[str] = []

        self._in_title = False
        self._table: TableData | None = None
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None
        self._cell_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()

        if tag == "title":
            self._in_title = True
            return

        if tag == "table":
            # BSM boxscore는 중첩 table을 사용하지 않는 전제로 첫 table만 연다.
            if self._table is None:
                self._table = TableData()
            return

        if self._table is None:
            return

        if tag == "tr":
            if self._row is None:
                self._row = []
            return

        if tag in {"th", "td"} and self._row is not None:
            if self._cell_parts is None:
                self._cell_parts = []
                self._cell_depth = 1
            else:
                self._cell_depth += 1
            return

        if tag == "br" and self._cell_parts is not None:
            self._cell_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag == "title":
            self._in_title = False
            return

        if self._table is None:
            return

        if tag in {"th", "td"} and self._cell_parts is not None:
            self._cell_depth -= 1
            if self._cell_depth <= 0:
                assert self._row is not None
                self._row.append(normalize_text("".join(self._cell_parts)))
                self._cell_parts = None
                self._cell_depth = 0
            return

        if tag == "tr" and self._row is not None:
            if any(cell != "" for cell in self._row):
                self._table.rows.append(self._row)
            self._row = None
            self._cell_parts = None
            self._cell_depth = 0
            return

        if tag == "table":
            if self._table.rows:
                self.tables.append(self._table)
            self._table = None
            self._row = None
            self._cell_parts = None
            self._cell_depth = 0

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    @property
    def title(self) -> str:
        return normalize_text("".join(self.title_parts))


def rows_to_dicts(header: list[str], rows: list[list[str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    width = len(header)
    for row in rows:
        padded = list(row[:width]) + [""] * max(0, width - len(row))
        result.append({header[i]: padded[i] for i in range(width)})
    return result


def header_set(header: list[str]) -> set[str]:
    return {normalize_text(x).upper() for x in header if normalize_text(x)}


def is_linescore_header(header: list[str]) -> bool:
    hs = header_set(header)
    return {"R", "H", "E"}.issubset(hs) and any(str(n) in hs for n in range(1, 13))


def is_batting_header(header: list[str]) -> bool:
    hs = header_set(header)
    required = {"AB", "R", "H", "RBI", "K", "BB", "AVG", "OPS"}
    return required.issubset(hs)


def is_pitching_header(header: list[str]) -> bool:
    hs = header_set(header)
    required = {"IP", "BF", "AB", "H", "R", "ER", "K", "BB", "ERA"}
    return required.issubset(hs)


def team_from_first_header(value: str, role: str) -> str:
    text = normalize_text(value)
    text = re.sub(rf"\s*\({re.escape(role)}\)\s*$", "", text, flags=re.I)
    return text.strip()


def parse_linescore(table: TableData) -> dict[str, Any]:
    if not table.rows:
        return {}
    header = table.rows[0]
    rows = rows_to_dicts(header, table.rows[1:])
    teams: list[dict[str, str]] = []
    team_key = header[0] if header else ""
    for row in rows:
        team = row.get(team_key, "")
        if not team:
            continue
        item = {"team": team}
        for key, value in row.items():
            if key == team_key:
                continue
            item[key] = value
        teams.append(item)
    return {"columns": header[1:], "teams": teams}


def parse_stat_table(table: TableData, role: str) -> dict[str, Any]:
    header = table.rows[0]
    first_header = header[0] if header else ""
    team = team_from_first_header(first_header, role)

    normalized_header = ["player"] + header[1:]
    players: list[dict[str, str]] = []
    totals: dict[str, str] | None = None

    for raw_row in table.rows[1:]:
        padded = list(raw_row[:len(header)]) + [""] * max(0, len(header) - len(raw_row))
        player_name = normalize_text(padded[0])

        item = {"player": player_name}
        for i, col in enumerate(header[1:], start=1):
            item[col] = padded[i] if i < len(padded) else ""

        if player_name:
            players.append(item)
        else:
            # BSM 합계행은 보통 첫 칸이 비어 있다.
            totals = {col: padded[i] if i < len(padded) else "" for i, col in enumerate(header[1:], start=1)}

    return {
        "team": team,
        "columns": normalized_header,
        "players": players,
        "totals": totals,
    }


def parse_boxscore_html(html_text: str, *, match_id: int | str | None = None) -> dict[str, Any]:
    parser = SimpleTableParser()
    parser.feed(html_text)
    parser.close()

    linescore: dict[str, Any] | None = None
    batting: list[dict[str, Any]] = []
    pitching: list[dict[str, Any]] = []
    debug_tables: list[dict[str, Any]] = []

    for idx, table in enumerate(parser.tables):
        if not table.rows:
            continue
        header = table.rows[0]

        if linescore is None and is_linescore_header(header):
            linescore = parse_linescore(table)
            continue

        if is_batting_header(header):
            batting.append(parse_stat_table(table, "Batters"))
            continue

        if is_pitching_header(header):
            pitching.append(parse_stat_table(table, "Pitchers"))
            continue

        debug_tables.append({
            "index": idx,
            "header": header,
            "row_count": max(0, len(table.rows) - 1),
        })

    return {
        "match_id": int(match_id) if str(match_id or "").isdigit() else match_id,
        "title": parser.title,
        "linescore": linescore,
        "batting": batting,
        "pitching": pitching,
        "unclassified_tables": debug_tables,
        "table_count": len(parser.tables),
    }


def has_boxscore_data(parsed: dict[str, Any]) -> bool:
    linescore = parsed.get("linescore")
    batting = parsed.get("batting") or []
    pitching = parsed.get("pitching") or []
    return bool(
        (isinstance(linescore, dict) and (linescore.get("teams") or []))
        and (batting or pitching)
    )


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_html(session: requests.Session, match_id: int | str) -> requests.Response:
    url = f"{BASE_URL}/matches/{match_id}/match_boxscore"
    return session.get(
        url,
        headers=BROWSER_HEADERS,
        timeout=TIMEOUT,
        allow_redirects=True,
    )


def find_candidate_file(script_dir: Path | None = None) -> Path | None:
    """Find candidate_matches.json independent of VS Code's current working directory."""
    script_dir = (script_dir or Path(__file__).resolve().parent).resolve()

    roots: list[Path] = []
    for root in [Path.cwd().resolve(), script_dir, *script_dir.parents]:
        if root not in roots:
            roots.append(root)

    relative_candidates = [
        Path("bsm_season_data/2025_discovery_v2/candidate_matches.json"),
        Path("tests/bsm_season_data/2025_discovery_v2/candidate_matches.json"),
    ]

    for root in roots:
        for relative in relative_candidates:
            candidate = root / relative
            if candidate.exists():
                return candidate
    return None


def default_candidate_file() -> Path | None:
    # Backward-compatible alias.
    return find_candidate_file()


def load_candidate_matches(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise TypeError("candidate_matches.json must contain a JSON list")
    return [row for row in data if isinstance(row, dict)]


def process_one_network(
    session: requests.Session,
    match_id: int | str,
    raw_dir: Path,
    parsed_dir: Path,
) -> dict[str, Any]:
    url = f"{BASE_URL}/matches/{match_id}/match_boxscore"
    row: dict[str, Any] = {
        "id": int(match_id) if str(match_id).isdigit() else match_id,
        "url": url,
    }

    try:
        response = fetch_html(session, match_id)
    except requests.RequestException as exc:
        row["status"] = "network_error"
        row["error"] = str(exc)
        return row

    row["http_status"] = response.status_code
    row["content_type"] = response.headers.get("content-type")

    if response.status_code != 200:
        row["status"] = f"http_{response.status_code}"
        return row

    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{match_id}.html"
    raw_path.write_text(response.text, encoding=response.encoding or "utf-8")
    row["raw_html"] = str(raw_path)

    parsed = parse_boxscore_html(response.text, match_id=match_id)
    parsed_path = parsed_dir / f"{match_id}.json"
    save_json(parsed_path, parsed)
    row["parsed_json"] = str(parsed_path)
    row["title"] = parsed.get("title")
    row["table_count"] = parsed.get("table_count")
    row["batting_tables"] = len(parsed.get("batting") or [])
    row["pitching_tables"] = len(parsed.get("pitching") or [])
    row["status"] = "available" if has_boxscore_data(parsed) else "html_200_unparsed"
    return row


def make_report(rows: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1

    lines = ["===== BSM Boxscore HTML v3 =====", ""]
    lines.append(f"Processed: {len(rows)}")
    for status in sorted(counts):
        lines.append(f"{status}: {counts[status]}")

    available = counts.get("available", 0)
    coverage = available / len(rows) * 100 if rows else 0.0
    lines.append(f"Parsed coverage: {available}/{len(rows)} ({coverage:.1f}%)")
    lines.append("")
    lines.append("JSON .json endpoint is not used here; this version reads the public HTML Boxscore page.")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch and parse public BSM Boxscore HTML pages.")
    parser.add_argument("--match-id", type=int, help="Process only one match ID.")
    parser.add_argument("--html-file", type=Path, help="Parse one already-downloaded HTML file offline.")
    parser.add_argument("--candidate-file", type=Path, help="Path to 2025_discovery_v2/candidate_matches.json")
    parser.add_argument("--batch", action="store_true", help="Process candidate_matches.json in batch mode.")
    parser.add_argument("--probe-all", action="store_true", help="Also request matches with statistics_published_flag=false.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of batch requests for testing.")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="Delay between requests in seconds.")
    parser.add_argument("--output", type=Path, default=None, help="Output directory.")
    args = parser.parse_args(argv)

    # VS Code F5 / "Run Python File" commonly supplies no CLI arguments.
    # In that case, do the safe one-game test instead of accidentally entering batch mode.
    batch_hint = args.batch or args.candidate_file is not None or args.limit is not None or args.probe_all
    if args.match_id is None and args.html_file is None and not batch_hint:
        args.match_id = 59028

    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Offline parse mode
    if args.html_file:
        if not args.html_file.exists():
            print(f"ERROR: HTML file not found: {args.html_file}", file=sys.stderr)
            return 1
        text = args.html_file.read_text(encoding="utf-8", errors="replace")
        match_id = args.match_id
        if match_id is None:
            m = re.search(r"(\d+)", args.html_file.stem)
            match_id = int(m.group(1)) if m else None
        parsed = parse_boxscore_html(text, match_id=match_id)
        out = args.output or Path("bsm_boxscore_debug") / str(match_id or "offline")
        out.mkdir(parents=True, exist_ok=True)
        parsed_path = out / "parsed_boxscore.json"
        save_json(parsed_path, parsed)
        print("Parsed:", parsed_path)
        print("Title:", parsed.get("title"))
        print("Linescore:", "OK" if parsed.get("linescore") else "NO")
        print("Batting tables:", len(parsed.get("batting") or []))
        print("Pitching tables:", len(parsed.get("pitching") or []))
        print("Overall:", "OK" if has_boxscore_data(parsed) else "UNPARSED")
        return 0 if has_boxscore_data(parsed) else 2

    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)

    # Single network match mode
    if args.match_id is not None:
        out = args.output or Path("bsm_boxscore_html_v3")
        raw_dir = out / "raw_html"
        parsed_dir = out / "parsed"
        row = process_one_network(session, args.match_id, raw_dir, parsed_dir)
        print(json.dumps(row, ensure_ascii=False, indent=2))
        return 0 if row.get("status") == "available" else 2

    candidate_file = args.candidate_file or find_candidate_file()
    if candidate_file is None:
        print(
            "ERROR: candidate_matches.json not found.\n"
            "Use --candidate-file PATH explicitly.",
            file=sys.stderr,
        )
        return 1

    matches = load_candidate_matches(candidate_file)
    if not args.probe_all:
        matches = [
            row for row in matches
            if row.get("statistics_published_flag") is True
        ]

    if args.limit is not None:
        matches = matches[:max(0, args.limit)]

    out = args.output or candidate_file.parent
    raw_dir = out / "boxscores_html_raw"
    parsed_dir = out / "boxscores_parsed"
    status_path = out / "html_boxscore_status.json"
    report_path = out / "html_boxscore_report.txt"

    print(f"Candidate file : {candidate_file}")
    print(f"Requests       : {len(matches)}")
    print(f"Output         : {out}")
    print()

    rows: list[dict[str, Any]] = []
    total = len(matches)

    for idx, match in enumerate(matches, start=1):
        match_id = match.get("id")
        if match_id is None:
            continue

        print(f"[{idx}/{total}] {match_id} ...", end=" ", flush=True)
        row = process_one_network(session, match_id, raw_dir, parsed_dir)
        row["statistics_published_flag"] = match.get("statistics_published_flag")
        row["candidate_leagues"] = match.get("candidate_leagues")
        row["match_id_label"] = match.get("match_id")
        row["home_team"] = match.get("home_team")
        row["away_team"] = match.get("away_team")
        print(row.get("status"))

        rows.append(row)
        save_json(status_path, rows)

        if args.delay > 0 and idx < total:
            time.sleep(args.delay)

    report = make_report(rows)
    report_path.write_text(report, encoding="utf-8")

    print()
    print(report, end="")
    print(f"Status file: {status_path}")
    print(f"Report     : {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
