"""The fast results path: filling in fixtures without duplicating them."""

import pytest

from vb.repo import find_match_near, upsert_match
from vb.sources import oddsapi


@pytest.fixture
def fixture_row(conn):
    """A fixture as the results feed would have left it: no score yet."""
    return upsert_match(conn, "E0", "2026/27", "2026-08-29T20:00:00",
                        "Tottenham Hotspur", "Newcastle United",
                        status="scheduled", source="football-data")


def _payload(commence: str, home="Tottenham Hotspur", away="Newcastle United",
             hg="2", ag="1", completed=True):
    return [{
        "home_team": home, "away_team": away, "commence_time": commence,
        "completed": completed,
        "scores": [{"name": home, "score": hg}, {"name": away, "score": ag}],
    }]


def _patch(monkeypatch, payload):
    monkeypatch.setattr(oddsapi, "api_key", lambda: "test-key")
    monkeypatch.setattr(oddsapi, "fetch_json", lambda *a, **k: payload)


def test_a_score_fills_in_the_fixture_we_already_had(conn, fixture_row, monkeypatch):
    _patch(monkeypatch, _payload("2026-08-29T20:00:00Z"))
    assert oddsapi.load_scores(conn, "E0", "2026/27") == 1
    rows = conn.execute("SELECT id, fthg, ftag, status FROM matches").fetchall()
    assert len(rows) == 1, "the score created a second row for the same match"
    assert (rows[0]["id"], rows[0]["fthg"], rows[0]["ftag"], rows[0]["status"]) \
        == (fixture_row, 2, 1, "played")


def test_a_kick_off_that_crosses_midnight_in_utc_is_the_same_match(conn, fixture_row,
                                                                   monkeypatch):
    """The trap: 20:45 in Italy is one date locally and the next in UTC.

    Matching on the exact calendar day would file the result as a separate
    fixture, silently splitting the club's record in two.
    """
    _patch(monkeypatch, _payload("2026-08-30T00:45:00Z"))
    assert oddsapi.load_scores(conn, "E0", "2026/27") == 1
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 1
    assert conn.execute("SELECT fthg FROM matches").fetchone()["fthg"] == 2


def test_a_genuinely_different_date_is_a_different_match(conn, fixture_row, monkeypatch):
    _patch(monkeypatch, _payload("2026-09-15T20:00:00Z"))
    oddsapi.load_scores(conn, "E0", "2026/27")
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 2


def test_a_richer_feed_is_not_overwritten(conn, monkeypatch):
    """football-data arrives later with shots and corners. Don't clobber it."""
    match_id = upsert_match(conn, "E0", "2026/27", "2026-08-29T20:00:00",
                            "Tottenham Hotspur", "Newcastle United",
                            fthg=3, ftag=0, hs=14, hc=8, source="football-data")
    _patch(monkeypatch, _payload("2026-08-29T20:00:00Z"))
    oddsapi.load_scores(conn, "E0", "2026/27")
    row = conn.execute("SELECT fthg, ftag, hs, hc FROM matches WHERE id = ?",
                       (match_id,)).fetchone()
    assert (row["fthg"], row["ftag"], row["hs"], row["hc"]) == (3, 0, 14, 8)


def test_matches_still_in_play_are_ignored(conn, fixture_row, monkeypatch):
    _patch(monkeypatch, _payload("2026-08-29T20:00:00Z", completed=False))
    assert oddsapi.load_scores(conn, "E0", "2026/27") == 0
    assert conn.execute("SELECT fthg FROM matches").fetchone()["fthg"] is None


def test_club_spellings_still_resolve(conn, fixture_row, monkeypatch):
    """The odds API says "Tottenham Hotspur"; football-data says "Tottenham"."""
    _patch(monkeypatch, _payload("2026-08-29T20:00:00Z", home="Tottenham",
                                 away="Newcastle"))
    assert oddsapi.load_scores(conn, "E0", "2026/27") == 1
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 1


def test_find_match_near_respects_its_window(conn, fixture_row):
    assert find_match_near(conn, "E0", "Tottenham", "Newcastle", "2026-08-30") is not None
    assert find_match_near(conn, "E0", "Tottenham", "Newcastle", "2026-09-02") is None


def test_an_older_database_gains_new_columns(tmp_path):
    """Columns added after the first release must reach existing databases.

    CREATE TABLE IF NOT EXISTS silently does nothing to a table that already
    exists, so without a migration step an upgraded install keeps the old
    schema. The schema also indexes one of the new columns, which is why the
    migration has to run before the schema script rather than after it.

    The "old" database is built by creating the current schema and dropping the
    new columns back off, which leaves a table genuinely lacking them — rather
    than by editing the SQL text, which is easy to get subtly wrong.
    """
    import sqlite3

    from vb.db import LATER_COLUMNS, SCHEMA, migrate, session

    if sqlite3.sqlite_version_info < (3, 35):
        pytest.skip("ALTER TABLE DROP COLUMN needs SQLite 3.35 or newer")

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(SCHEMA)
    for table, columns in LATER_COLUMNS.items():
        for column in columns:
            # Any index over the column has to go before the column can.
            for row in old.execute(
                    "SELECT name, sql FROM sqlite_master WHERE type = 'index'"
            ).fetchall():
                if row[1] and column in row[1]:
                    old.execute(f"DROP INDEX {row[0]}")
            old.execute(f'ALTER TABLE {table} DROP COLUMN "{column}"')
    old.execute("INSERT INTO leagues (code, name, country, tier) "
                "VALUES ('E0','Premier League','England',1)")
    old.commit()
    for table, columns in LATER_COLUMNS.items():
        present = {r[1] for r in old.execute(f"PRAGMA table_info({table})")}
        assert not (set(columns) & present), f"{table} still has the new columns"
    old.close()

    with session(path) as conn:
        for table, columns in LATER_COLUMNS.items():
            present = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for column in columns:
                assert column in present, f"{table}.{column} was not added"
        assert conn.execute("SELECT COUNT(*) FROM leagues").fetchone()[0] >= 1
        assert migrate(conn) == [], "migration should be idempotent"


def test_the_odds_quota_is_read_from_the_reply():
    """The-odds-api reports the monthly allowance in every response header."""
    from vb.sources import oddsapi

    oddsapi.QUOTA.clear()
    oddsapi._record_quota({"x-requests-remaining": "412", "x-requests-used": "88",
                           "X-Requests-Last": "1"})
    assert oddsapi.QUOTA["remaining"] == 412
    assert oddsapi.QUOTA["used"] == 88
    assert "412 requests left" in oddsapi.quota_summary()


def test_an_unknown_quota_says_so_rather_than_guessing():
    from vb.sources import oddsapi

    oddsapi.QUOTA.clear()
    assert "not yet known" in oddsapi.quota_summary()


def test_every_price_records_which_feed_it_came_from(conn, monkeypatch):
    """Guessing a price's origin from the bookmaker's name reports fiction.

    The health check claimed tens of thousands of prices had arrived "via the
    API" on a database the API had never been called for, because it inferred
    the source from which books were involved.
    """
    from vb.repo import upsert_match, upsert_odds
    from vb.sources import oddsapi

    match_id = upsert_match(conn, "E0", "2026/27", "2026-08-29T15:00:00",
                            "Liverpool", "Nottingham Forest", status="scheduled")
    upsert_odds(conn, match_id, "skybet", "h2h", "home", 1.50,
                source="football-data-fixtures")
    assert conn.execute(
        "SELECT COUNT(*) FROM odds WHERE source = 'odds-api'").fetchone()[0] == 0

    monkeypatch.setattr(oddsapi, "api_key", lambda: "k")
    monkeypatch.setattr(oddsapi, "_fetch_odds", lambda *a, **k: [{
        "home_team": "Liverpool", "away_team": "Nottingham Forest",
        "commence_time": "2026-08-29T15:00:00Z",
        "bookmakers": [{"key": "paddypower", "markets": [{"key": "h2h", "outcomes": [
            {"name": "Liverpool", "price": 1.55},
            {"name": "Nottingham Forest", "price": 6.2},
            {"name": "Draw", "price": 4.1}]}]}],
    }])
    oddsapi.load_league_odds(conn, "E0", "2026/27")
    assert conn.execute(
        "SELECT COUNT(*) FROM odds WHERE source = 'odds-api'").fetchone()[0] == 3
    assert conn.execute(
        "SELECT COUNT(*) FROM odds WHERE source = 'football-data-fixtures'"
    ).fetchone()[0] == 1
