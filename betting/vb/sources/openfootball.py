"""openfootball/football.json — an optional free fixtures/results feed.

Useful as a cross-check and for competitions the paid-for feeds skip. Coverage
is volunteer-maintained and patchy for European club competitions, so a missing
file is reported as a plain message rather than treated as an error.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..config import league as get_league
from ..repo import upsert_match
from .http import FetchError, fetch_text

BASE = "https://raw.githubusercontent.com/openfootball/football.json/master"

# league code -> openfootball file stem
FILE_STEMS = {
    "E0": "en.1", "E1": "en.2", "E2": "en.3", "E3": "en.4",
    "D1": "de.1", "I1": "it.1", "SP1": "es.1",
    "UCL": "cl", "UEL": "el",
}


def season_dir(season: str) -> str:
    """'2025/26' -> '2025-26'."""
    start, end = season.replace("/", "-").split("-")
    return f"{start}-{end[-2:]}"


def url_for(league_code: str, season: str) -> str:
    lg = get_league(league_code)
    stem = lg.openfootball or FILE_STEMS.get(league_code)
    if not stem:
        raise ValueError(f"no openfootball mapping for {league_code}")
    return f"{BASE}/{season_dir(season)}/{stem}.json"


def load_json_text(conn: sqlite3.Connection, league_code: str, season: str, text: str) -> int:
    data = json.loads(text)
    count = 0
    for match in data.get("matches", []):
        date = match.get("date")
        if not date:
            continue
        kickoff = f"{date}T{match.get('time', '19:00')}:00" if len(match.get("time", "")) == 5 \
            else f"{date}T19:00:00"
        score = match.get("score") or {}
        ft = score.get("ft") or []
        stats = {"source": "openfootball", "stage": match.get("round")}
        if len(ft) == 2:
            stats["fthg"], stats["ftag"] = int(ft[0]), int(ft[1])
        ht = score.get("ht") or []
        if len(ht) == 2:
            stats["hthg"], stats["htag"] = int(ht[0]), int(ht[1])
        upsert_match(
            conn, league_code, season, kickoff,
            match["team1"], match["team2"], **stats,
        )
        count += 1
    return count


def load_season(conn: sqlite3.Connection, league_code: str, season: str,
                force: bool = False) -> int:
    url = url_for(league_code, season)
    try:
        text = fetch_text(url, max_age=6 * 3600, suffix=".json", force=force)
    except FetchError as exc:
        raise FetchError(
            f"openfootball has no {league_code} file for {season} ({url}). "
            "This feed is volunteer-maintained and skips most recent European "
            "competition seasons — use the odds API or a manual CSV instead."
        ) from exc
    return load_json_text(conn, league_code, season, text)


def load_file(conn: sqlite3.Connection, league_code: str, season: str, path: str | Path) -> int:
    return load_json_text(conn, league_code, season, Path(path).read_text())
