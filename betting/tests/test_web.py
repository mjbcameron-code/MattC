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


def test_the_health_tab_accounts_for_what_the_engine_saw(conn, loaded_app, client):
    """Silence from a league must be explained, not just absent."""
    from vb.db import set_setting
    from vb.market.value import Trace
    from vb.tips.select import build_tipsheet

    body = client.get("/").get_data(as_text=True)
    assert "Build the card" in body, "with no account yet, say how to get one"

    trace = Trace()
    build_tipsheet(conn, days=7, season="2026/27", include_outrights=False,
                   trace=trace)
    set_setting(conn, "coverage.trace", trace.to_json())
    conn.commit()

    body = client.get("/").get_data(as_text=True)
    assert "What the engine saw" in body
    assert "prices" in body
    # the reasons themselves have to reach the page, not just the totals
    assert "edge below the minimum" in body or "no price on file" in body


def test_a_league_with_no_prices_says_so_on_the_page(conn, loaded_app, client):
    from vb.db import set_setting
    from vb.market.value import Trace
    from vb.tips.select import gather

    conn.execute("DELETE FROM odds")
    trace = Trace()
    gather(conn, days=7, trace=trace)
    set_setting(conn, "coverage.trace", trace.to_json())
    conn.commit()

    body = client.get("/").get_data(as_text=True)
    assert "no price on file" in body
    assert "none tipped" in body


def test_the_trace_survives_the_round_trip_through_the_database(conn):
    from vb.market.value import Trace

    trace = Trace()
    trace.note("EC", "edge below the minimum", 63)
    trace.note("EC", "tipped", 2)
    back = Trace.from_json(trace.to_json())
    assert back.rows("EC") == trace.rows("EC")
    assert back.total("EC") == trace.total("EC")


def test_the_health_tab_shows_how_far_short_a_price_fell(conn, loaded_app, client):
    """"83 below the minimum" is ambiguous unless the sizes are visible.

    83 near misses at 3.9% and 83 at 0.2% call for opposite responses.
    """
    from vb.db import set_setting
    from vb.market.value import Trace
    from vb.tips.select import build_tipsheet

    trace = Trace()
    build_tipsheet(conn, days=7, season="2026/27", include_outrights=False,
                   trace=trace)
    set_setting(conn, "coverage.trace", trace.to_json())
    conn.commit()

    body = client.get("/").get_data(as_text=True)
    assert "Strongest edges found" in body
    assert "of the say" in body and "matches per club" in body


def test_the_magnitudes_survive_the_database(conn):
    from vb.market.value import Trace

    trace = Trace()
    trace.saw_edge("EC", 0.039, "Woking v Barnet: h2h home at 2.10")
    trace.note_setup("EC", 0.127, 4)
    back = Trace.from_json(trace.to_json())
    assert back.near_misses("EC") == [(0.039, "Woking v Barnet: h2h home at 2.10")]
    summary = back.weight("EC")
    assert summary["fixtures"] == 1
    assert summary["weight_mid"] == 0.127 and summary["seen_mid"] == 4


def test_a_trace_saved_before_magnitudes_existed_still_loads(conn):
    """An older database holds the bare counts with no wrapper."""
    from vb.market.value import Trace

    back = Trace.from_json('{"EC": {"edge below the minimum": 83}}')
    assert back.rows("EC") == [("edge below the minimum", 83)]
    assert back.near_misses("EC") == []
    assert back.weight("EC") is None


def test_only_the_strongest_near_misses_are_kept(conn):
    from vb.market.value import Trace

    trace = Trace()
    for i in range(40):
        trace.saw_edge("EC", i / 1000, f"bet {i}")
    kept = trace.near_misses("EC")
    assert len(kept) == Trace.KEEP
    assert [round(e, 3) for e, _ in kept] == [0.039, 0.038, 0.037, 0.036, 0.035]


def test_a_record_from_an_older_build_says_so(conn, loaded_app, client):
    """Rendered silently, a stale record is indistinguishable from a fresh one.

    Both show counts and nothing else, so the reader concludes the engine had
    nothing more to say rather than that they are looking at yesterday.
    """
    from vb.db import set_setting

    set_setting(conn, "coverage.trace", '{"EC": {"edge below the minimum": 83}}')
    set_setting(conn, "coverage.built_at", "2026-08-31T09:15:00")
    conn.commit()

    body = client.get("/").get_data(as_text=True)
    assert "saved by an older version" in body
    assert "31 August, 09:15" in body


def test_a_record_with_every_field_but_an_older_shape_is_still_stale(
        conn, loaded_app, client):
    """The hole the first staleness check had.

    This record carries counts, near misses and a weight — everything the
    reader looks for — but holds the weight in the older single-value shape.
    Converted for display it reports "across 1 fixtures", which is not a
    measurement of anything, and nothing said so.
    """
    from vb.db import set_setting

    set_setting(conn, "coverage.trace", (
        '{"counts": {"EC": {"edge below the minimum": 83}}, '
        '"best": {"EC": [[0.286, "Harrogate v Gateshead"]]}, '
        '"setup": {"EC": {"weight": 0.35, "matches_seen": 95}}}'))
    set_setting(conn, "coverage.built_at", "2026-08-31T13:31:00")
    conn.commit()

    body = client.get("/").get_data(as_text=True)
    assert "saved by an older version" in body


def test_a_fresh_record_carries_no_warning(conn, loaded_app, client):
    from vb.db import set_setting
    from vb.market.value import Trace
    from vb.tips.select import build_tipsheet

    trace = Trace()
    build_tipsheet(conn, days=7, season="2026/27", include_outrights=False,
                   trace=trace)
    set_setting(conn, "coverage.trace", trace.to_json())
    set_setting(conn, "coverage.built_at", "2026-08-31T09:15:00")
    conn.commit()

    body = client.get("/").get_data(as_text=True)
    assert "saved by an older version" not in body
    assert "Recorded 31 August, 09:15" in body
