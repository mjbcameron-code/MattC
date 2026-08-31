"""The longshot lane: outsiders admitted on their own terms, not on relaxed ones."""

import pytest

from vb.config import load_settings
from vb.sample import generate_all
from vb.tips.select import choose_singles, gather


@pytest.fixture
def opened(conn):
    """Longshots on, so the lane is actually exercised."""
    settings = load_settings()
    block = settings.raw["selection"]
    before = block.get("longshots")
    block["longshots"] = {
        "enabled": True, "max_odds": 34.0, "min_edge": 0.10,
        "min_prob_edge": 0.005, "min_signals": 3, "max_stake_pts": 0.5,
    }
    generate_all(conn, season="2026/27", leagues=["E2", "E3"], seed=12)
    yield conn
    if before is None:
        block.pop("longshots", None)
    else:
        block["longshots"] = before


def _longshots(candidates, ceiling):
    return [c for c in candidates if c.price > ceiling]


def test_a_longshot_must_clear_a_fatter_edge_than_a_normal_bet(opened):
    settings = load_settings()
    ceiling = float(settings.get("selection.max_odds", 12.0))
    candidates, _, _ = gather(opened, days=7)
    for candidate in _longshots(candidates, ceiling):
        assert candidate.edge >= 0.10 - 1e-9, (
            f"{candidate.selection_text()} at {candidate.price}: "
            f"{candidate.edge:.1%} is an ordinary bet's bar, not a longshot's")
        assert candidate.longshot


def test_a_longshot_is_staked_small_whatever_kelly_says(opened):
    settings = load_settings()
    ceiling = float(settings.get("selection.max_odds", 12.0))
    candidates, _, _ = gather(opened, days=7)
    for candidate in _longshots(candidates, ceiling):
        assert candidate.stake_pts <= 0.5, (
            f"{candidate.selection_text()} at {candidate.price} staked "
            f"{candidate.stake_pts}")


def test_nothing_beyond_the_longshot_ceiling_survives(opened):
    candidates, _, _ = gather(opened, days=7)
    assert all(c.price <= 34.0 for c in candidates)


def test_turning_the_lane_off_restores_the_old_ceiling(conn):
    settings = load_settings()
    block = settings.raw["selection"]
    before = block.get("longshots")
    block["longshots"] = {"enabled": False}
    try:
        generate_all(conn, season="2026/27", leagues=["E2", "E3"], seed=12)
        candidates, _, _ = gather(conn, days=7)
        ceiling = float(settings.get("selection.max_odds", 12.0))
        assert all(c.price <= ceiling for c in candidates)
        assert not any(c.longshot for c in candidates)
    finally:
        if before is None:
            block.pop("longshots", None)
        else:
            block["longshots"] = before


def test_a_longshot_needs_more_corroboration_than_an_ordinary_bet(opened):
    """The "fancied for good reason" half of the bargain."""
    from vb.market.value import Trace

    settings = load_settings()
    ceiling = float(settings.get("selection.max_odds", 12.0))
    candidates, _, _ = gather(opened, days=7)
    trace = Trace()
    chosen = choose_singles(candidates, trace=trace)

    for candidate in chosen:
        if candidate.price > ceiling:
            assert len(candidate.supporting_signals()) >= 3 or any(
                s.strength >= 0.75 for s in candidate.supporting_signals()), (
                f"{candidate.selection_text()} at {candidate.price} was tipped "
                f"on {len(candidate.supporting_signals())} signal(s)")

    # And when one is turned down for that, the report says which test it failed.
    reasons = {r for code in trace.leagues() for r, _ in trace.rows(code)}
    assert "not enough supporting signals" in reasons or \
           "longshot without enough corroboration" in reasons
