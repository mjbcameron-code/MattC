"""Tip -> ledger -> settlement -> figures, the loop the whole thing exists to run."""

from datetime import datetime, timedelta

import pytest

from vb.report import dashboard
from vb.sample import generate_all
from vb.tips.select import build_tipsheet
from vb.track import metrics
from vb.track.ledger import all_bets, legs_for, record_tipsheet
from vb.track.settle import settle_bets


@pytest.fixture
def loaded(conn):
    """Two divisions, with the season paused mid-week so fixtures lie ahead."""
    generate_all(conn, season="2025/26", leagues=["E2", "E3"], seed=11)
    return conn


def test_a_card_is_produced_and_reads_like_english(loaded):
    sheet = build_tipsheet(loaded, days=7, season="2025/26", include_outrights=False)
    assert sheet.all_tips, "the engine found nothing to bet on synthetic soft prices"
    assert sheet.bet_of_the_week is not None
    assert sheet.bet_of_the_week.headline.startswith("Bet of the Week:")
    for tip in sheet.all_tips:
        assert tip.stake_pts > 0
        assert tip.price > 1.0
        assert len(tip.body) > 60
        assert 1 <= tip.confidence <= 5
        assert tip.body[0].isupper() and tip.body.rstrip().endswith((".", "!"))


def test_stakes_respect_the_configured_caps(loaded):
    sheet = build_tipsheet(loaded, days=7, season="2025/26", include_outrights=False)
    for tip in sheet.singles:
        assert 0.25 <= tip.stake_pts <= 3.0
        assert (tip.stake_pts * 100) % 25 == 0        # quarter-point steps


def test_no_two_bets_on_the_same_angle(loaded):
    sheet = build_tipsheet(loaded, days=7, season="2025/26", include_outrights=False)
    from vb.tips.select import MARKET_FAMILY
    seen = set()
    for tip in sheet.singles:
        key = (tip.match_id, MARKET_FAMILY.get(tip.raw_market, tip.raw_market))
        assert key not in seen, f"two bets on the same angle: {tip.selection}"
        seen.add(key)


def test_the_ledger_records_and_does_not_duplicate(loaded):
    sheet = build_tipsheet(loaded, days=7, season="2025/26", include_outrights=False)
    first = record_tipsheet(loaded, sheet)
    assert sum(first.values()) == len(sheet.all_tips)
    assert record_tipsheet(loaded, sheet) == {}, "re-running must not double the ledger"
    for bet in all_bets(loaded):
        assert legs_for(loaded, bet["id"]), f"{bet['ref']} was stored with no legs"


def test_settlement_closes_the_loop(loaded):
    """Tip the past, settle it, and check the arithmetic of the points column."""
    as_of = datetime.now() - timedelta(weeks=12)
    sheet = build_tipsheet(loaded, days=7, as_of=as_of, season="2025/26",
                           include_outrights=False, statuses=("played",))
    record_tipsheet(loaded, sheet)
    settle_bets(loaded)

    settled = [b for b in all_bets(loaded) if b["status"] != "pending"]
    assert settled, "nothing settled even though the results are all in"
    for bet in settled:
        stake, returned = float(bet["stake_pts"]), float(bet["returned_pts"])
        assert float(bet["pnl_pts"]) == pytest.approx(returned - stake)
        if bet["status"] == "won" and bet["bet_type"] != "acca":
            assert returned == pytest.approx(stake * float(bet["price"]))
        if bet["status"] == "lost":
            assert returned == 0.0

    summary = metrics.summarise(loaded)
    assert summary.settled == len(settled)
    assert summary.pnl == pytest.approx(sum(float(b["pnl_pts"]) for b in settled))
    assert summary.staked == pytest.approx(sum(float(b["stake_pts"]) for b in settled))


def test_the_dashboard_renders(loaded):
    sheet = build_tipsheet(loaded, days=7, season="2025/26", include_outrights=False)
    record_tipsheet(loaded, sheet)
    html = dashboard.render(dashboard.build_context(loaded, sheet, synthetic=True))
    assert "<title>" in html and "Demonstration data" in html
    assert "GambleAware" in html
    # every theme token must be defined on bare :root, not only inside a media query
    root_block = html.split(":root {", 1)[1].split("}", 1)[0]
    for token in ("--paper", "--card", "--ink", "--profit", "--loss", "--hero-bg"):
        assert token in root_block, f"{token} is not defined for the default theme"
