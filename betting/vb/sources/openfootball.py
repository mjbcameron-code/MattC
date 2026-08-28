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
    "D1": "de.1", "D2": "de.2", "I1": "it.1", "I2": "it.2",
    "SP1": "es.1", "SP2": "es.2",
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


def _matches_in(data) -> list[dict]:
    """Pull the match list out of whichever shape the file uses."""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    if isinstance(data.get("matches"), list):
        return data["matches"]
    matches: list[dict] = []
    for round_ in data.get("rounds", []) or []:
        matches.extend(round_.get("matches", []) or [])
    return matches


def _score(match: dict) -> tuple[list, list]:
    """Return (full time, half time) goals.

    The feed is inconsistent: most entries carry ``{"ft": [1, 0], "ht": [...]}``
    but a fair number use a bare ``[1, 0]`` instead, and an unplayed fixture has
    no score at all. All three shapes appear in the same file.
    """
    score = match.get("score")
    if isinstance(score, list):
        return (score, [])
    if isinstance(score, dict):
        return (score.get("ft") or [], score.get("ht") or [])
    return ([], [])


def load_json_text(conn: sqlite3.Connection, league_code: str, season: str, text: str) -> int:
    data = json.loads(text)
    count = 0
    for match in _matches_in(data):
        date = match.get("date")
        if not date or not match.get("team1") or not match.get("team2"):
            continue
        time = match.get("time") or ""
        kickoff = f"{date}T{time}:00" if len(time) == 5 else f"{date}T19:00:00"
        ft, ht = _score(match)
        stats = {"source": "openfootball", "stage": match.get("round")}
        if len(ft) == 2 and all(x is not None for x in ft):
            stats["fthg"], stats["ftag"] = int(ft[0]), int(ft[1])
        if len(ht) == 2 and all(x is not None for x in ht):
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
