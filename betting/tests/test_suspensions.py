"""Suspensions derived from red cards — team news without a paid feed."""

from datetime import datetime, timedelta

import pytest

from vb.features.form import team_news
from vb.features.suspensions import SOURCE, derive_suspensions
from vb.repo import upsert_match


@pytest.fixture
def sent_off(conn):
    """A red card on Saturday, and the same club playing again on Wednesday."""
    now = datetime.now()
    upsert_match(conn, "E0", "2026/27", (now - timedelta(days=3)).isoformat(),
                 "Arsenal", "Chelsea", fthg=1, ftag=1, hr=1, ar=0, status="played")
    upsert_match(conn, "E0", "2026/27", (now + timedelta(days=4)).isoformat(),
                 "Everton", "Arsenal", status="scheduled")
    return conn


def test_a_sending_off_becomes_an_absence_in_the_next_match(sent_off):
    assert derive_suspensions(sent_off) == 1
    row = sent_off.execute(
        "SELECT n.kind, n.impact, n.source, n.match_id, t.name FROM team_news n "
        "JOIN teams t ON t.id = n.team_id").fetchone()
    assert row["name"] == "Arsenal"
    assert row["kind"] == "suspension"
    assert row["source"] == SOURCE
    assert row["impact"] > 0
    assert row["match_id"] is not None, "it must attach to the specific fixture"


def test_the_team_that_kept_eleven_men_is_untouched(sent_off):
    derive_suspensions(sent_off)
    names = [r["name"] for r in sent_off.execute(
        "SELECT t.name FROM team_news n JOIN teams t ON t.id = n.team_id")]
    assert "Chelsea" not in names


def test_running_it_twice_writes_nothing_the_second_time(sent_off):
    assert derive_suspensions(sent_off) == 1
    assert derive_suspensions(sent_off) == 0


def test_two_reds_count_for_more_than_one(conn):
    now = datetime.now()
    upsert_match(conn, "E0", "2026/27", (now - timedelta(days=2)).isoformat(),
                 "Alpha", "Beta", fthg=0, ftag=2, hr=2, ar=0, status="played")
    upsert_match(conn, "E0", "2026/27", (now + timedelta(days=5)).isoformat(),
                 "Alpha", "Gamma", status="scheduled")
    derive_suspensions(conn)
    row = conn.execute("SELECT impact, player FROM team_news").fetchone()
    assert row["player"] == "players"
    assert row["impact"] == pytest.approx(0.14)


def test_a_ban_applies_to_the_next_match_only(sent_off):
    """A one-game suspension must not follow the club around for a fortnight."""
    now = datetime.now()
    later = upsert_match(sent_off, "E0", "2026/27",
                         (now + timedelta(days=9)).isoformat(),
                         "Arsenal", "Fulham", status="scheduled")
    derive_suspensions(sent_off)
    arsenal = sent_off.execute("SELECT id FROM teams WHERE name = 'Arsenal'").fetchone()["id"]

    next_up = sent_off.execute(
        "SELECT id FROM matches WHERE status = 'scheduled' ORDER BY kickoff LIMIT 1"
    ).fetchone()["id"]
    assert team_news(sent_off, arsenal, now, match_id=next_up)
    assert not team_news(sent_off, arsenal, now, match_id=later), \
        "the ban has been served by then"


def test_nothing_is_written_when_there_is_no_next_fixture(conn):
    now = datetime.now()
    upsert_match(conn, "E0", "2026/27", (now - timedelta(days=2)).isoformat(),
                 "Alpha", "Beta", fthg=0, ftag=0, hr=1, status="played")
    assert derive_suspensions(conn) == 0


def test_an_old_red_card_is_out_of_scope(conn):
    now = datetime.now()
    upsert_match(conn, "E0", "2026/27", (now - timedelta(days=200)).isoformat(),
                 "Alpha", "Beta", fthg=0, ftag=0, hr=1, status="played")
    upsert_match(conn, "E0", "2026/27", (now + timedelta(days=2)).isoformat(),
                 "Alpha", "Gamma", status="scheduled")
    assert derive_suspensions(conn) == 0


def test_the_absence_moves_the_model(conn):
    """The point of all this: a side a man light should be rated lower."""
    from vb.models.fixture import ModelBank, build_fixture
    from vb.sample import generate_league

    now = datetime.now()
    generate_league(conn, "E3", "2026/27", now - timedelta(weeks=32),
                    played_fraction=0.7, seed=5)
    fixture_row = conn.execute(
        "SELECT * FROM matches WHERE status = 'scheduled' ORDER BY kickoff LIMIT 1"
    ).fetchone()

    before = build_fixture(conn, fixture_row, ModelBank(conn), with_players=False)
    conn.execute(
        "INSERT INTO team_news (team_id, match_id, player, kind, detail, impact, "
        "source, added_at) VALUES (?,?,?,?,?,?,?,?)",
        (fixture_row["home_id"], fixture_row["id"], "a player", "suspension",
         "sent off", 0.10, SOURCE, now.date().isoformat()),
    )
    after = build_fixture(conn, fixture_row, ModelBank(conn), with_players=False)
    assert after.probs.lam_home < before.probs.lam_home
    assert after.probs.lam_away > before.probs.lam_away
