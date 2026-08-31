"""The local app: the parts a static report cannot do."""

import pytest

from vb.track.ledger import mark_passed, mark_placed


@pytest.fixture
def client(loaded_app):
    from vb.web.app import app

    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def loaded_app(conn, tmp_path, monkeypatch):
    """A database with a card on it, wired up to the app."""
    from datetime import datetime, timedelta

    from vb.sample import generate_all
    from vb.tips.select import build_tipsheet
    from vb.track.ledger import record_tipsheet
    from vb.web.app import app

    generate_all(conn, season="2026/27", leagues=["E2"], seed=3)
    sheet = build_tipsheet(conn, days=7, season="2026/27", include_outrights=False)
    record_tipsheet(conn, sheet)
    conn.commit()
    app.config["DB_PATH"] = conn.execute("PRAGMA database_list").fetchone()["file"]
    return app.config["DB_PATH"]


def test_the_page_loads_with_the_card_on_it(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "This week&#39;s card" in body or "This week's card" in body
    assert "I backed this" in body
    assert "GambleAware" in body


def test_the_page_declares_its_encoding(client):
    """Served or saved, the page has to say it is UTF-8 or the dashes break."""
    body = client.get("/").get_data(as_text=True)
    assert '<meta charset="utf-8">' in body


def test_marking_a_bet_records_the_price_you_actually_got(conn, loaded_app):
    ref = conn.execute("SELECT ref FROM bets LIMIT 1").fetchone()["ref"]
    assert mark_placed(conn, ref, price=3.25, stake=1.5)
    row = conn.execute("SELECT placed, placed_price, placed_stake FROM bets "
                       "WHERE ref = ?", (ref,)).fetchone()
    assert row["placed"] == 1
    assert row["placed_price"] == pytest.approx(3.25)
    assert row["placed_stake"] == pytest.approx(1.5)


def test_advice_stands_whether_or_not_it_was_backed(conn, loaded_app):
    """Two records, deliberately: how good the tips are, and how you did."""
    ref = conn.execute("SELECT ref FROM bets LIMIT 1").fetchone()["ref"]
    before = conn.execute("SELECT price, stake_pts, status FROM bets WHERE ref = ?",
                          (ref,)).fetchone()
    mark_placed(conn, ref, price=9.99, stake=0.25)
    after = conn.execute("SELECT price, stake_pts, status FROM bets WHERE ref = ?",
                         (ref,)).fetchone()
    assert (after["price"], after["stake_pts"], after["status"]) == \
           (before["price"], before["stake_pts"], before["status"]), \
           "the advised terms must not be rewritten by what you did"


def test_passing_clears_it_again(conn, loaded_app):
    ref = conn.execute("SELECT ref FROM bets LIMIT 1").fetchone()["ref"]
    mark_placed(conn, ref, 2.0, 1.0)
    assert mark_passed(conn, ref)
    row = conn.execute("SELECT placed, placed_price FROM bets WHERE ref = ?",
                       (ref,)).fetchone()
    assert row["placed"] == 0 and row["placed_price"] is None


def test_your_record_counts_only_what_you_backed(conn, loaded_app):
    from vb.web.app import _placed_summary

    assert _placed_summary(conn)["bets"] == 0, "nothing backed yet"
    refs = [r["ref"] for r in conn.execute("SELECT ref FROM bets LIMIT 2")]
    for ref in refs:
        mark_placed(conn, ref, price=2.0, stake=1.0)
    conn.execute("UPDATE bets SET status = 'won' WHERE ref = ?", (refs[0],))
    conn.execute("UPDATE bets SET status = 'lost' WHERE ref = ?", (refs[1],))
    summary = _placed_summary(conn)
    assert summary["bets"] == 2
    assert summary["staked"] == pytest.approx(2.0)
    assert summary["pnl"] == pytest.approx(0.0)   # +1.0 won, -1.0 lost


def test_an_unknown_reference_is_refused(conn, loaded_app):
    assert not mark_placed(conn, "no-such-bet", 2.0, 1.0)
    assert not mark_passed(conn, "no-such-bet")
