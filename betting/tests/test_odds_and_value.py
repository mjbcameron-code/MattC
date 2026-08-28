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
