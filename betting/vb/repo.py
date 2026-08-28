"""Team and match resolution — the layer every data source writes through.

Feeds disagree about club names: football-data.co.uk says "Man United",
the-odds-api says "Manchester United", openfootball says "Manchester United FC".
Everything is funnelled through :func:`resolve_team`, which keeps one canonical
row per club and records every spelling it has seen as an alias.
"""

from __future__ import annotations

import difflib
import re
import sqlite3
import unicodedata
from functools import lru_cache
from datetime import datetime, timezone
from typing import Any

import yaml

from .config import CONFIG_DIR

# Tokens that carry no identifying information once you are inside a league.
_NOISE = {
    "fc", "afc", "cf", "sc", "ac", "as", "ss", "ssc", "us", "usc", "sv", "vfl",
    "vfb", "tsg", "fsv", "bsc", "sg", "spvgg", "rb", "cd", "ud", "rcd", "sd",
    "club", "de", "futbol", "calcio", "the", "1899", "1846", "1900", "1904",
    "05", "04", "1907", "1893", "1909",
}
# Words that separate two clubs sharing a place name: Manchester United vs
# Manchester City, Bristol City vs Bristol Rovers, Oldham Athletic vs Oldham.
_SUFFIXES = ("united", "city", "town", "rovers", "albion", "wanderers",
             "county", "athletic", "argyle", "alexandra", "thistle",
             "stanley", "forest", "villa", "hotspur", "orient")


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )


def normalise(name: str) -> str:
    """Aggressive normalisation used only for fuzzy matching, never for display."""
    text = _strip_accents(name).lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    tokens = [t for t in text.split() if t and t not in _NOISE]
    return " ".join(tokens)


def distinguishing(name: str) -> set[str]:
    """The suffixes that separate two clubs from the same town.

    Manchester United and Manchester City share a place name and nothing else.
    Any matcher that treats "United" and "City" as noise will merge them — and
    merging two clubs silently corrupts every result, rating and settled bet
    that follows. So a name carrying one of these words can only ever match a
    name carrying the same one.
    """
    return {t for t in normalise(name).split() if t in _SUFFIXES}


def suffix_conflict(a: str, b: str) -> bool:
    """True when two names carry different distinguishing suffixes."""
    sa, sb = distinguishing(a), distinguishing(b)
    return bool(sa) and bool(sb) and sa != sb


# Short forms the feeds use that a character-level matcher will never link up.
_ABBREV = {
    "utd": "united", "man": "manchester", "nottm": "nottingham",
    "sheff": "sheffield", "weds": "wednesday", "wed": "wednesday",
    "boro": "borough", "peterboro": "peterborough", "wolves": "wolverhampton",
    "spurs": "tottenham", "hibs": "hibernian", "qpr": "queens park rangers",
    "dag": "dagenham", "red": "redbridge", "ath": "athletic",
    "atl": "atletico", "rvs": "rovers", "co": "county", "acad": "academical",
    "ct": "caledonian thistle", "gladbach": "monchengladbach",
    "st": "saint", "inter": "internazionale", "mgladbach": "monchengladbach",
}


def _tokens(name: str) -> list[str]:
    out: list[str] = []
    for token in normalise(name).split():
        out.extend(_ABBREV.get(token, token).split())
    return out


def token_similarity(a: str, b: str) -> float:
    """Token-set similarity where a short token may abbreviate a longer one.

    'Man United' and 'Manchester United' share both tokens once 'man' is
    allowed to stand in for 'manchester', which a plain character-level
    comparison scores at only ~0.8.
    """
    if suffix_conflict(a, b):
        return 0.0
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    unused = list(tb)
    matched = 0.0
    for token in ta:
        best, best_score = None, 0.0
        for cand in unused:
            if token == cand:
                score = 1.0
            elif len(token) >= 3 and cand.startswith(token):
                score = 0.9
            elif len(cand) >= 3 and token.startswith(cand):
                score = 0.9
            else:
                score = difflib.SequenceMatcher(None, token, cand).ratio()
                score = score if score > 0.85 else 0.0
            if score > best_score:
                best, best_score = cand, score
        if best is not None and best_score > 0:
            matched += best_score
            unused.remove(best)
    return matched / max(len(ta), len(tb))


_ALIAS_FILE = CONFIG_DIR / "aliases.yaml"


@lru_cache(maxsize=1)
def curated_aliases() -> dict[str, str]:
    """Hand-maintained spelling -> canonical name map for the awkward cases."""
    if not _ALIAS_FILE.exists():
        return {}
    with open(_ALIAS_FILE) as fh:
        raw = yaml.safe_load(fh) or {}
    return {str(k).strip().lower(): str(v).strip() for k, v in (raw.get("aliases") or {}).items()}


def resolve_team(
    conn: sqlite3.Connection,
    name: str,
    league_code: str | None = None,
    country: str | None = None,
    source: str | None = None,
    create: bool = True,
) -> int | None:
    """Return the team id for ``name``, creating or aliasing it as needed."""
    raw = (name or "").strip()
    if not raw:
        return None
    canonical = curated_aliases().get(raw.lower(), raw)
    key = canonical.strip().lower()

    row = conn.execute("SELECT team_id FROM team_aliases WHERE alias = ?", (key,)).fetchone()
    if row:
        return row["team_id"]

    row = conn.execute(
        "SELECT id FROM teams WHERE lower(name) = ?", (key,)
    ).fetchone()
    if row:
        _link_alias(conn, key, row["id"], source)
        return row["id"]

    # Fuzzy match, preferring clubs already known in the same league.
    candidates = conn.execute(
        "SELECT id, name, league_code FROM teams"
    ).fetchall()
    best_id, best_score = None, 0.0
    target_norm = normalise(canonical)
    for cand in candidates:
        cand_norm = normalise(cand["name"])
        if not cand_norm or not target_norm:
            continue
        if suffix_conflict(canonical, cand["name"]):
            continue
        score = max(
            difflib.SequenceMatcher(None, target_norm, cand_norm).ratio(),
            token_similarity(canonical, cand["name"]),
        )
        if league_code and cand["league_code"] == league_code:
            score += 0.04
        if score > best_score:
            best_id, best_score = cand["id"], score
    if best_id is not None and best_score >= 0.90:
        _link_alias(conn, key, best_id, source)
        return best_id

    if not create:
        return None

    cur = conn.execute(
        "INSERT INTO teams (name, country, league_code) VALUES (?,?,?)",
        (canonical, country, league_code),
    )
    team_id = int(cur.lastrowid)
    _link_alias(conn, key, team_id, source)
    return team_id


def _link_alias(conn: sqlite3.Connection, alias: str, team_id: int, source: str | None) -> None:
    conn.execute(
        "INSERT INTO team_aliases (alias, team_id, source) VALUES (?,?,?) "
        "ON CONFLICT(alias) DO NOTHING",
        (alias, team_id, source),
    )


def team_name(conn: sqlite3.Connection, team_id: int) -> str:
    row = conn.execute("SELECT name FROM teams WHERE id = ?", (team_id,)).fetchone()
    return row["name"] if row else f"#{team_id}"


def set_team_league(conn: sqlite3.Connection, team_id: int, league_code: str) -> None:
    conn.execute("UPDATE teams SET league_code = ? WHERE id = ?", (league_code, team_id))


# ---------------------------------------------------------------------------
# matches
# ---------------------------------------------------------------------------
_MATCH_STAT_COLUMNS = (
    "status", "stage", "referee", "fthg", "ftag", "hthg", "htag", "hs", "as",
    "hst", "ast", "hc", "ac", "hf", "af", "hy", "ay", "hr", "ar",
    "home_xg", "away_xg", "source", "kickoff",
)


def upsert_match(
    conn: sqlite3.Connection,
    league_code: str,
    season: str,
    kickoff: str,
    home: str,
    away: str,
    **stats: Any,
) -> int:
    """Insert or update one match. ``stats`` may hold any column in the schema."""
    home_id = resolve_team(conn, home, league_code, source=stats.get("source"))
    away_id = resolve_team(conn, away, league_code, source=stats.get("source"))
    if home_id is None or away_id is None:
        raise ValueError(f"could not resolve teams: {home!r} v {away!r}")
    match_date = kickoff[:10]

    existing = conn.execute(
        "SELECT id FROM matches WHERE league_code=? AND season=? AND home_id=? "
        "AND away_id=? AND match_date=?",
        (league_code, season, home_id, away_id, match_date),
    ).fetchone()

    payload = {k: v for k, v in stats.items() if k in _MATCH_STAT_COLUMNS and v is not None}
    payload.setdefault("kickoff", kickoff)
    if payload.get("fthg") is not None and payload.get("ftag") is not None:
        payload.setdefault("status", "played")

    if existing:
        match_id = existing["id"]
        if payload:
            sets = ", ".join(f'"{k}" = ?' for k in payload)
            conn.execute(
                f"UPDATE matches SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (*payload.values(), match_id),
            )
        return match_id

    record = {
        "league_code": league_code,
        "season": season,
        "match_date": match_date,
        "home_id": home_id,
        "away_id": away_id,
        **payload,          # includes kickoff
    }
    quoted = ", ".join(f'"{c}"' for c in record)
    placeholders = ", ".join("?" for _ in record)
    cur = conn.execute(
        f"INSERT INTO matches ({quoted}) VALUES ({placeholders})", list(record.values())
    )
    return int(cur.lastrowid)


def upsert_odds(
    conn: sqlite3.Connection,
    match_id: int,
    bookmaker: str,
    market: str,
    selection: str,
    price: float,
    line: float | None = None,
    taken_at: str | None = None,
    is_closing: bool = False,
) -> None:
    conn.execute(
        "INSERT INTO odds (match_id, bookmaker, market, selection, line, price, "
        "taken_at, is_closing) VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(match_id, bookmaker, market, selection, line, taken_at) "
        "DO UPDATE SET price = excluded.price, is_closing = excluded.is_closing",
        (
            match_id, bookmaker.lower(), market, selection, line, float(price),
            taken_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            int(is_closing),
        ),
    )


def find_match(
    conn: sqlite3.Connection, league_code: str, home: str, away: str, date: str | None = None
) -> sqlite3.Row | None:
    home_id = resolve_team(conn, home, league_code, create=False)
    away_id = resolve_team(conn, away, league_code, create=False)
    if home_id is None or away_id is None:
        return None
    if date:
        return conn.execute(
            "SELECT * FROM matches WHERE league_code=? AND home_id=? AND away_id=? "
            "AND match_date=?",
            (league_code, home_id, away_id, date[:10]),
        ).fetchone()
    return conn.execute(
        "SELECT * FROM matches WHERE league_code=? AND home_id=? AND away_id=? "
        "ORDER BY kickoff DESC LIMIT 1",
        (league_code, home_id, away_id),
    ).fetchone()
