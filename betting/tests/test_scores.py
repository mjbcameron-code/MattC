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
    """
    import re
    import sqlite3

    from vb.db import LATER_COLUMNS, SCHEMA, migrate, session

    old_schema = SCHEMA
    for table, columns in LATER_COLUMNS.items():
        for column in columns:
            old_schema = re.sub(rf"^\s*{column}\b.*$", "", old_schema, flags=re.M)
            old_schema = re.sub(rf"^.*CREATE INDEX.*\({column}\).*$", "",
                                old_schema, flags=re.M)
    assert "api_fixture_id" not in old_schema

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(old_schema)
    old.execute("INSERT INTO leagues (code, name, country, tier) "
                "VALUES ('E0','Premier League','England',1)")
    old.commit()
    old.close()

    with session(path) as conn:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(matches)")}
        assert "api_fixture_id" in columns
        assert conn.execute("SELECT COUNT(*) FROM leagues").fetchone()[0] >= 1
        assert migrate(conn) == [], "migration should be idempotent"
