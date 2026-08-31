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


def _settled_bet(conn, ref: str, price: float, won: bool, stake: float = 1.0):
    """One graded bet, with every column the schema insists on."""
    conn.execute(
        "INSERT INTO bets (ref, placed_at, event_date, bet_type, headline, "
        "selection, market, league_code, price, stake_pts, model_prob, edge, "
        "reasoning, confidence, status, returned_pts, pnl_pts) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ref, "2026-01-09", "2026-01-10", "single", f"{ref} headline",
         "Arsenal", "h2h", "E0", price, stake, 1 / price, 0.0, "because", 3,
         "won" if won else "lost",
         stake * price if won else 0.0,
         stake * (price - 1) if won else -stake))


def test_the_roi_carries_its_own_uncertainty(conn):
    """A headline ROI over a couple of hundred bets invites a false conclusion.

    At these prices the noise is wider than any edge a model of this kind could
    plausibly have, so the standard error has to travel with the number.
    """
    from vb.track import metrics

    # Twenty-eight bets at 4.00, seven of them winners. Break-even at that
    # price is a one-in-four strike, so this book is exactly level: +21, -21.
    for i in range(28):
        _settled_bet(conn, f"T{i:03d}", 4.0, won=(i % 4 == 0))
    conn.commit()

    summary = metrics.summarise(conn)
    assert summary.settled == 28
    assert summary.pnl == pytest.approx(0.0, abs=1e-9)
    assert summary.roi == pytest.approx(0.0, abs=1e-9)
    # Returns of +3 or -1 have a spread of about 1.76 per unit staked, so a
    # dead-level book still carries a standard error of a third of the stake.
    # That is the whole point: -9% over 181 bets says almost nothing.
    assert summary.roi_stderr == pytest.approx(0.333, abs=0.01)


def test_a_short_priced_book_is_much_less_noisy(conn):
    """The point of the number: the same ROI means more at 1.5 than at 8.0."""
    from vb.track import metrics

    for i in range(30):
        _settled_bet(conn, f"S{i:03d}", 1.5, won=(i % 3 != 0))
    conn.commit()
    tight = metrics.summarise(conn).roi_stderr

    conn.execute("DELETE FROM bets")
    for i in range(30):
        _settled_bet(conn, f"L{i:03d}", 8.0, won=(i % 8 == 0))
    conn.commit()
    loose = metrics.summarise(conn).roi_stderr

    assert loose > tight * 2, f"{loose:.3f} should dwarf {tight:.3f}"


def test_no_uncertainty_is_claimed_from_a_single_bet(conn):
    from vb.track import metrics

    _settled_bet(conn, "T1", 4.0, won=True)
    conn.commit()
    assert metrics.summarise(conn).roi_stderr == 0.0


def test_a_price_we_invented_does_not_count_as_a_measurement(conn):
    """A bet builder is advised at a target we compute, and settled at it.

    So raising the price we demand improves the record without a single bet
    changing — which is exactly what happened when builder legs were shaded.
    Those bets carry no bookmaker, and that is what tells them apart.
    """
    from vb.track import metrics

    for i in range(10):                      # real quotes, level book
        _settled_bet(conn, f"R{i:03d}", 4.0, won=(i % 4 == 0))
    conn.execute("UPDATE bets SET bookmaker = 'bet365'")
    for i in range(10):                      # invented target prices, all losers
        _settled_bet(conn, f"B{i:03d}", 6.0, won=False)
    conn.commit()

    everything = metrics.summarise(conn)
    measured = metrics.summarise(conn, priced_only=True)

    assert everything.settled == 20 and measured.settled == 10
    assert measured.pnl > everything.pnl, "the invented bets must be excluded"
    assert measured.staked == 10.0
