"""SQLite storage: schema, connection handling and small upsert helpers."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from .config import DB_PATH, ensure_dirs, load_leagues

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS leagues (
    code      TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    country   TEXT NOT NULL,
    tier      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS teams (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    country      TEXT,
    league_code  TEXT REFERENCES leagues(code)
);

-- Source feeds spell club names differently ("Man Utd" / "Manchester United"
-- / "Man United"). Every spelling seen is recorded here and resolved to one
-- canonical team row.
CREATE TABLE IF NOT EXISTS team_aliases (
    alias    TEXT PRIMARY KEY,
    team_id  INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    source   TEXT
);

CREATE TABLE IF NOT EXISTS matches (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    league_code  TEXT NOT NULL REFERENCES leagues(code),
    season       TEXT NOT NULL,
    kickoff      TEXT NOT NULL,           -- ISO 8601, UTC
    match_date   TEXT NOT NULL,           -- YYYY-MM-DD, for identity
    home_id      INTEGER NOT NULL REFERENCES teams(id),
    away_id      INTEGER NOT NULL REFERENCES teams(id),
    status       TEXT NOT NULL DEFAULT 'scheduled',  -- scheduled | played
    stage        TEXT,                    -- league phase, QF, etc (UEFA)
    referee      TEXT,
    fthg INTEGER, ftag INTEGER,           -- full time goals
    hthg INTEGER, htag INTEGER,           -- half time goals
    hs   INTEGER, "as" INTEGER,           -- shots
    hst  INTEGER, ast INTEGER,            -- shots on target
    hc   INTEGER, ac  INTEGER,            -- corners
    hf   INTEGER, af  INTEGER,            -- fouls
    hy   INTEGER, ay  INTEGER,            -- yellow cards
    hr   INTEGER, ar  INTEGER,            -- red cards
    home_xg REAL, away_xg REAL,           -- real xG where a feed exists
    api_fixture_id INTEGER,               -- the id this match has at API-Football
    source  TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (league_code, season, home_id, away_id, match_date)
);

CREATE INDEX IF NOT EXISTS idx_matches_league_date ON matches(league_code, kickoff);
CREATE INDEX IF NOT EXISTS idx_matches_api_id ON matches(api_fixture_id);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status, kickoff);

CREATE TABLE IF NOT EXISTS odds (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id    INTEGER REFERENCES matches(id) ON DELETE CASCADE,
    bookmaker   TEXT NOT NULL,
    market      TEXT NOT NULL,            -- h2h | totals | btts | ah | corners…
    selection   TEXT NOT NULL,            -- home | draw | away | over | under…
    line        REAL,                     -- goal/corner/handicap line, else NULL
    price       REAL NOT NULL,            -- decimal odds
    taken_at    TEXT NOT NULL,
    is_closing  INTEGER NOT NULL DEFAULT 0,
    source      TEXT,                    -- which feed produced this price
    UNIQUE (match_id, bookmaker, market, selection, line, taken_at)
);

CREATE INDEX IF NOT EXISTS idx_odds_match ON odds(match_id, market);

-- Outright / season-long markets, which hang off a league rather than a match.
CREATE TABLE IF NOT EXISTS outright_odds (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    league_code TEXT NOT NULL REFERENCES leagues(code),
    season      TEXT NOT NULL,
    market      TEXT NOT NULL,            -- winner | top_four | relegation…
    selection   TEXT NOT NULL,            -- team or player name
    bookmaker   TEXT NOT NULL,
    price       REAL NOT NULL,
    taken_at    TEXT NOT NULL,
    UNIQUE (league_code, season, market, selection, bookmaker, taken_at)
);

CREATE TABLE IF NOT EXISTS team_news (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id    INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    match_id   INTEGER REFERENCES matches(id) ON DELETE CASCADE,
    player     TEXT NOT NULL,
    kind       TEXT NOT NULL,             -- injury | suspension | doubt | return
    detail     TEXT,
    impact     REAL NOT NULL DEFAULT 0.0, -- 0..1 share of team strength affected
    source     TEXT,
    added_at   TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_news_team ON team_news(team_id, added_at);

CREATE TABLE IF NOT EXISTS player_stats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player      TEXT NOT NULL,
    team_id     INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    league_code TEXT NOT NULL REFERENCES leagues(code),
    season      TEXT NOT NULL,
    position    TEXT,
    apps        INTEGER DEFAULT 0,
    minutes     INTEGER DEFAULT 0,
    goals       INTEGER DEFAULT 0,
    shots       INTEGER DEFAULT 0,
    sot         INTEGER DEFAULT 0,
    fouls       INTEGER DEFAULT 0,
    tackles     INTEGER DEFAULT 0,
    yellows     INTEGER DEFAULT 0,
    reds        INTEGER DEFAULT 0,
    updated_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (player, team_id, season)
);

CREATE TABLE IF NOT EXISTS referees (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    league_code TEXT,
    games       INTEGER DEFAULT 0,
    yellows     INTEGER DEFAULT 0,
    reds        INTEGER DEFAULT 0,
    fouls       INTEGER DEFAULT 0,
    updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Fitted attack/defence strengths, snapshotted each time the model is run.
CREATE TABLE IF NOT EXISTS ratings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    league_code TEXT NOT NULL REFERENCES leagues(code),
    team_id     INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    as_of       TEXT NOT NULL,
    attack      REAL NOT NULL,
    defence     REAL NOT NULL,
    matches     INTEGER NOT NULL,
    UNIQUE (league_code, team_id, as_of)
);

CREATE TABLE IF NOT EXISTS league_params (
    league_code TEXT NOT NULL REFERENCES leagues(code),
    as_of       TEXT NOT NULL,
    home_adv    REAL NOT NULL,
    rho         REAL NOT NULL,           -- Dixon-Coles low-score correction
    base_goals  REAL NOT NULL,
    base_corners REAL,
    base_cards  REAL,
    PRIMARY KEY (league_code, as_of)
);

-- ---------------------------------------------------------------------------
-- The tip ledger
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ref          TEXT NOT NULL UNIQUE,     -- human reference, e.g. 2025W34-03
    placed_at    TEXT NOT NULL,
    event_date   TEXT NOT NULL,
    league_code  TEXT REFERENCES leagues(code),
    bet_type     TEXT NOT NULL,            -- single | acca | builder | outright
    headline     TEXT NOT NULL,            -- "Bet of the Week: …"
    selection    TEXT NOT NULL,            -- human readable selection
    market       TEXT,
    bookmaker    TEXT,
    price        REAL NOT NULL,
    stake_pts    REAL NOT NULL,
    model_prob   REAL NOT NULL,
    fair_prob    REAL,                     -- market's devigged probability
    edge         REAL NOT NULL,
    confidence   INTEGER NOT NULL DEFAULT 3,  -- 1..5 stars
    reasoning    TEXT NOT NULL,
    signals      TEXT,                     -- JSON list of supporting signals
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending|won|lost|void|
                                                   -- half_won|half_lost
    returned_pts REAL,
    pnl_pts      REAL,
    closing_price REAL,
    clv          REAL,                     -- closing line value
    settled_at   TEXT,
    notes        TEXT
);

CREATE INDEX IF NOT EXISTS idx_bets_status ON bets(status, event_date);

CREATE TABLE IF NOT EXISTS bet_legs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    bet_id     INTEGER NOT NULL REFERENCES bets(id) ON DELETE CASCADE,
    leg_no     INTEGER NOT NULL,
    match_id   INTEGER REFERENCES matches(id) ON DELETE SET NULL,
    market     TEXT NOT NULL,
    selection  TEXT NOT NULL,
    line       REAL,
    subject    TEXT,                       -- player name for player markets
    price      REAL,
    model_prob REAL,
    status     TEXT NOT NULL DEFAULT 'pending',
    UNIQUE (bet_id, leg_no)
);

CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    ensure_dirs()
    target = Path(path) if path else DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Columns added after the first release. CREATE TABLE IF NOT EXISTS will not
# add a column to a table that already exists, so they are applied separately.
LATER_COLUMNS = {
    "matches": {"api_fixture_id": "INTEGER"},
    "odds": {"source": "TEXT"},
}


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Add any columns a database created by an earlier version is missing.

    This has to run *before* the schema script, not after: the script creates an
    index over one of the new columns, and on an old database that fails before
    anything else has a chance to run. Tables that do not exist yet are skipped,
    so a fresh database falls straight through to the schema.
    """
    applied: list[str] = []
    tables = {row["name"] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    for table, columns in LATER_COLUMNS.items():
        if table not in tables:
            continue
        existing = {row["name"] for row in
                    conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for column, kind in columns.items():
            if column not in existing:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN "{column}" {kind}')
                applied.append(f"{table}.{column}")
    return applied


def init_db(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    """Create the schema (idempotent), apply migrations, seed the leagues."""
    own = conn is None
    conn = conn or connect()
    migrate(conn)
    conn.executescript(SCHEMA)
    for lg in load_leagues().values():
        conn.execute(
            "INSERT INTO leagues (code, name, country, tier) VALUES (?,?,?,?) "
            "ON CONFLICT(code) DO UPDATE SET name=excluded.name, "
            "country=excluded.country, tier=excluded.tier",
            (lg.code, lg.name, lg.country, lg.tier),
        )
    conn.commit()
    if own:
        return conn
    return conn


@contextmanager
def session(path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    conn = init_db(connect(path))
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None):
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO kv (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]
