"""Real match-level xG from understat.com (top five leagues only).

Understat ships its data as escaped JSON inside a <script> block. Where a
league has no understat page — every English division below the Premier
League, all of Scotland, the National League — the model falls back to the
shot-based xG proxy in vb/models/xg.py.
"""

from __future__ import annotations

import json
import re
import sqlite3

from ..config import league as get_league
from ..repo import find_match
from .http import fetch_text

BASE = "https://understat.com/league"
_BLOCK = re.compile(r"var\s+(\w+)\s*=\s*JSON\.parse\('([^']+)'\)")


def season_start(season: str) -> str:
    """'2025/26' -> '2025' (understat labels a season by its opening year)."""
    return season.split("/")[0]


def parse_blocks(html: str) -> dict[str, object]:
    """Pull every `var X = JSON.parse('…')` payload out of an understat page."""
    out: dict[str, object] = {}
    for name, payload in _BLOCK.findall(html):
        try:
            decoded = payload.encode("utf-8").decode("unicode_escape")
            out[name] = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return out


def load_season(conn: sqlite3.Connection, league_code: str, season: str,
                force: bool = False) -> int:
    """Attach real xG to matches already in the database. Returns rows updated."""
    lg = get_league(league_code)
    if not lg.understat:
        return 0
    html = fetch_text(
        f"{BASE}/{lg.understat}/{season_start(season)}",
        max_age=6 * 3600, suffix=".html", force=force,
    )
    blocks = parse_blocks(html)
    fixtures = blocks.get("datesData") or []
    updated = 0
    for entry in fixtures:
        if not entry.get("isResult"):
            continue
        xg = entry.get("xG") or {}
        home_xg, away_xg = xg.get("h"), xg.get("a")
        if home_xg is None or away_xg is None:
            continue
        home = (entry.get("h") or {}).get("title")
        away = (entry.get("a") or {}).get("title")
        when = (entry.get("datetime") or "")[:10]
        row = find_match(conn, league_code, home, away, when)
        if row is None:
            # understat kickoff dates occasionally differ by a day from
            # football-data's; fall back to the most recent meeting.
            row = find_match(conn, league_code, home, away)
        if row is None:
            continue
        conn.execute(
            "UPDATE matches SET home_xg = ?, away_xg = ? WHERE id = ?",
            (float(home_xg), float(away_xg), row["id"]),
        )
        updated += 1
    return updated
