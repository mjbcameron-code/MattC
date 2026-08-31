"""Devigging, staking, and the guard against betting on nothing."""

import pytest

from vb.market.odds import (devig_odds_ratio, devig_proportional, devig_shin,
                            overround)
from vb.market.value import blend, confidence_weight, kelly_fraction
from vb.tips.language import format_price, to_fractional


@pytest.mark.parametrize("method", [devig_proportional, devig_odds_ratio, devig_shin])
def test_devig_returns_a_distribution(method):
    fair = method([1.50, 4.20, 7.00])
    assert sum(fair) == pytest.approx(1.0)
    assert all(0 < p < 1 for p in fair)


@pytest.mark.parametrize("method", [devig_proportional, devig_odds_ratio, devig_shin])
def test_devig_leaves_a_fair_book_alone(method):
    assert method([2.0, 2.0]) == pytest.approx([0.5, 0.5])


def test_shin_takes_more_margin_off_the_outsider():
    """The favourite-longshot bias is the reason for using Shin at all."""
    prices = [1.50, 4.20, 7.00]
    shin = devig_shin(prices)
    proportional = devig_proportional(prices)
    assert shin[0] > proportional[0]      # favourite ends up more likely
    assert shin[-1] < proportional[-1]    # outsider less so


def test_overround_is_measured_correctly():
    assert overround([2.0, 2.0]) == pytest.approx(0.0)
    assert overround([1.90, 1.90]) == pytest.approx(2 / 1.9 - 1)


def test_kelly_matches_the_textbook():
    assert kelly_fraction(0.55, 2.00) == pytest.approx(0.10)
    assert kelly_fraction(0.60, 2.00) == pytest.approx(0.20)


def test_kelly_never_stakes_on_a_losing_bet():
    assert kelly_fraction(0.50, 2.00) == 0.0
    assert kelly_fraction(0.40, 2.00) == 0.0


def test_kelly_scales_down_for_a_push():
    """A handicap that pushes a fifth of the time is a smaller bet than one that cannot."""
    without = kelly_fraction(0.55, 2.00, 0.0)
    with_push = kelly_fraction(0.44, 2.00, 0.20)
    assert 0 < with_push < without


def test_blend_moves_between_the_two_views():
    assert blend(0.6, 0.5, 1.0) == pytest.approx(0.6)
    assert blend(0.6, 0.5, 0.0) == pytest.approx(0.5)
    middle = blend(0.6, 0.5, 0.5)
    assert 0.5 < middle < 0.6


def test_blend_ignores_a_missing_market_price():
    assert blend(0.6, None, 0.4) == 0.6


def test_confidence_weight_grows_with_evidence():
    weights = [confidence_weight(0.4, n) for n in (0, 4, 10, 30, 100)]
    assert weights[0] == 0.0
    assert weights == sorted(weights)
    assert weights[-1] < 0.4          # never exceeds the configured ceiling


def test_fractional_odds_use_the_bookmakers_ladder():
    assert to_fractional(2.0) == "1/1"
    assert to_fractional(1.91) == "10/11"
    assert to_fractional(4.33) == "10/3"
    assert to_fractional(6.0) == "5/1"


def test_a_fraction_is_only_shown_when_it_is_honest():
    """3.61 is not 5/2, so the fraction is dropped rather than quoting a shorter price."""
    assert format_price(3.0) == "3.00 (2/1)"
    assert format_price(3.61) == "3.61"


@pytest.mark.parametrize("push", [0.0, 0.25, 0.5])
def test_expected_value_over_price_is_the_edge_in_probability_points(push):
    """Dividing the edge by the price converts it back into probability.

    This is what lets one rule cover handicaps as well as everything else: a
    push returns the stake, and the identity still holds.
    """
    p_win, price = 0.30, 3.5
    expected_value = p_win * price + push - 1
    assert expected_value / price == pytest.approx(p_win - (1 - push) / price)


def test_a_percentage_edge_is_not_a_fixed_amount_of_evidence():
    """The reason the probability floor exists, stated as arithmetic."""
    edge = 0.04
    # What a 4% edge asks you to disagree with the price by, in probability.
    at_short = edge / 1.50
    at_long = edge / 23.00
    assert at_short > 0.026 and at_long < 0.002
    assert at_short > 15 * at_long


def test_the_trace_funnel_adds_up(conn):
    """Every price is accounted for exactly once, and the two stages nest."""
    from vb.market.value import Trace
    from vb.sample import generate_all
    from vb.tips.select import choose_singles, gather

    generate_all(conn, season="2026/27", leagues=["E2", "E3"], seed=5)
    trace = Trace()
    candidates, _, _ = gather(conn, days=7, trace=trace)
    chosen = choose_singles(candidates, trace=trace)

    assert trace.leagues(), "nothing was traced at all"
    for code in trace.leagues():
        counts = dict(trace.rows(code))
        priced = counts.get("priced up", 0)
        cut = Trace.ORDER.index("priced up")
        # The pricing stage accounts for every price exactly once.
        assert trace.total(code) == sum(
            counts.get(r, 0) for r in Trace.ORDER[:cut]) + priced
        # And the discipline stage is a partition of what pricing let through.
        assert sum(counts.get(r, 0) for r in Trace.ORDER[cut + 1:]) == priced

    assert sum(dict(trace.rows(c)).get("tipped", 0)
               for c in trace.leagues()) == len(chosen)
    assert sum(dict(trace.rows(c)).get("priced up", 0)
               for c in trace.leagues()) == len(candidates)


def test_the_trace_tells_no_prices_apart_from_no_value(conn):
    """The distinction the whole thing exists for."""
    from vb.market.value import Trace
    from vb.sample import generate_all
    from vb.tips.select import gather

    generate_all(conn, season="2026/27", leagues=["E2"], seed=5)
    conn.execute("DELETE FROM odds")
    trace = Trace()
    gather(conn, days=7, trace=trace)
    # Not "for each league" — an empty tally would satisfy that without
    # reporting anything, which is the failure this is here to catch.
    assert trace.leagues() == ["E2"], "the silent league must still be named"
    reasons = dict(trace.rows("E2"))
    assert reasons.get("no price on file", 0) > 0
    assert reasons.get("priced up", 0) == 0


def test_the_weight_summary_is_a_spread_not_the_last_fixture():
    """One number per league is not a property of the league.

    An established club carries three seasons; a relegated one carries three
    games. Reporting whichever was scanned last reads as a fact about the
    competition and is not one — it sent me to a wrong conclusion once.
    """
    from vb.market.value import Trace

    trace = Trace()
    trace.note_setup("EC", 0.10, 3)
    trace.note_setup("EC", 0.35, 95)
    trace.note_setup("EC", 0.30, 40)
    summary = trace.weight("EC")
    assert summary["fixtures"] == 3
    assert summary["weight_low"] == 0.10 and summary["weight_high"] == 0.35
    assert summary["weight_mid"] == 0.30
    assert summary["seen_low"] == 3 and summary["seen_high"] == 95


def test_an_older_single_value_weight_record_still_loads():
    from vb.market.value import Trace

    back = Trace.from_json(
        '{"counts": {}, "best": {}, '
        '"setup": {"EC": {"weight": 0.35, "matches_seen": 95}}}')
    summary = back.weight("EC")
    assert summary["fixtures"] == 1 and summary["weight_mid"] == 0.35


def test_the_weight_summary_is_a_spread_not_the_last_fixture():
    """One number per league is not a property of the league.

    An established club carries three seasons; a relegated one carries three
    games. Reporting whichever was scanned last reads as a fact about the
    competition and is not one — it sent me to a wrong conclusion once.
    """
    from vb.market.value import Trace

    trace = Trace()
    trace.note_setup("EC", 0.10, 3)
    trace.note_setup("EC", 0.35, 95)
    trace.note_setup("EC", 0.30, 40)
    summary = trace.weight("EC")
    assert summary["fixtures"] == 3
    assert summary["weight_low"] == 0.10 and summary["weight_high"] == 0.35
    assert summary["weight_mid"] == 0.30
    assert summary["seen_low"] == 3 and summary["seen_high"] == 95


def test_an_older_single_value_weight_record_still_loads():
    from vb.market.value import Trace

    back = Trace.from_json(
        '{"counts": {}, "best": {}, '
        '"setup": {"EC": {"weight": 0.35, "matches_seen": 95}}}')
    summary = back.weight("EC")
    assert summary["fixtures"] == 1 and summary["weight_mid"] == 0.35
