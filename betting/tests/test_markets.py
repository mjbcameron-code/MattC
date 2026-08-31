"""The market maths has to be internally consistent or nothing downstream means anything."""

import math

import pytest

from vb.models.counts import CountProbs, over_probability
from vb.models.match import MatchProbs, score_matrix


@pytest.fixture
def probs():
    return MatchProbs(1.62, 1.08, rho=-0.06)


def test_score_matrix_is_a_distribution(probs):
    assert probs.matrix.sum() == pytest.approx(1.0)
    assert (probs.matrix >= 0).all()


def test_result_probabilities_sum_to_one(probs):
    assert probs.home_win + probs.draw + probs.away_win == pytest.approx(1.0)


def test_totals_are_complementary(probs):
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        assert probs.total_over(line) + probs.total_under(line) == pytest.approx(1.0)


def test_totals_are_monotone(probs):
    overs = [probs.total_over(line) for line in (0.5, 1.5, 2.5, 3.5, 4.5)]
    assert overs == sorted(overs, reverse=True)


def test_double_chance_matches_its_parts(probs):
    assert probs.double_chance("1X") == pytest.approx(probs.home_win + probs.draw)
    assert probs.double_chance("X2") == pytest.approx(probs.draw + probs.away_win)
    assert probs.double_chance("12") == pytest.approx(probs.home_win + probs.away_win)


def test_level_handicap_equals_draw_no_bet(probs):
    """A 0.0 handicap and draw-no-bet are the same bet, so they must price the same."""
    assert probs.ah_break_even(0.0, "home") == pytest.approx(probs.draw_no_bet("home"))


def test_half_ball_handicap_equals_the_match_result(probs):
    win, push, loss = probs.asian_handicap(-0.5, "home")
    assert push == pytest.approx(0.0)
    assert win == pytest.approx(probs.home_win)


def test_quarter_handicap_outcomes_sum_to_one(probs):
    for line in (-0.25, 0.25, -0.75, 1.25):
        assert sum(probs.asian_handicap(line, "home")) == pytest.approx(1.0)


def test_rho_zero_is_independent_poisson():
    matrix = score_matrix(1.6, 1.1, 0.0)
    expected = (math.exp(-1.6) * 1.6 ** 2 / 2) * (math.exp(-1.1) * 1.1)
    assert matrix[2, 1] == pytest.approx(expected, rel=1e-6)


def test_dixon_coles_moves_the_low_scores():
    """A negative rho must lift 0-0 and 1-1 — that is the whole point of the correction."""
    plain = score_matrix(1.3, 1.1, 0.0)
    corrected = score_matrix(1.3, 1.1, -0.1)
    assert corrected[0, 0] > plain[0, 0]
    assert corrected[1, 1] > plain[1, 1]


def test_negative_binomial_is_wider_than_poisson():
    """Corner totals are overdispersed; the negative binomial must reflect that."""
    poisson = over_probability(10.5, 9.5, 0)
    negbin = over_probability(10.5, 9.5, 12)
    assert negbin < poisson          # more spread, less mass just above the mean
    assert over_probability(10.5, 20.5, 12) > over_probability(10.5, 20.5, 0)


def test_count_over_under_complementary():
    counts = CountProbs(6.0, 4.5, dispersion=14.0)
    for line in (7.5, 9.5, 11.5):
        assert counts.over(line) + counts.under(line) == pytest.approx(1.0)


def test_most_corners_three_way_sums_to_one():
    counts = CountProbs(6.0, 4.5, dispersion=14.0)
    total = counts.most("home") + counts.most("draw") + counts.most("away")
    assert total == pytest.approx(1.0, abs=1e-9)


def test_booking_points_match_card_lines_when_no_reds():
    counts = CountProbs(1.9, 2.1, dispersion=10.0)
    # A tiny gap remains because "no reds" is modelled as a Poisson with a
    # near-zero mean rather than a hard zero.
    assert counts.booking_points_over(25.5, 0.0) == pytest.approx(counts.over(2.5), abs=1e-5)


# ---------------------------------------------------------------------------
# Asian handicaps: one line convention, or the market cannot be devigged
# ---------------------------------------------------------------------------
def test_both_sides_of_a_handicap_share_one_line(probs):
    """`line` is the handicap on the home team, for both selections.

    Storing the away side under the mirrored line split every handicap into two
    one-sided books. Devigging needs a complete market, so it declined to touch
    them, and every handicap was priced on the raw model with nothing to blend
    against — the exact over-confidence the blending exists to correct.
    """
    for line in (-2.75, -1.5, -0.5, 0.0, 0.75, 2.0):
        home = probs.probability("ah", "home", line)
        away = probs.probability("ah", "away", line)
        assert home + away == pytest.approx(1.0), f"line {line} does not pair up"


def test_giving_a_bigger_start_makes_the_away_side_likelier(probs):
    """Sanity of direction: the more the home team concedes, the better away is."""
    generous = probs.probability("ah", "away", -2.5)   # home gives 2.5
    stingy = probs.probability("ah", "away", 0.5)      # home receives 0.5
    assert generous > stingy


def test_a_handicap_market_can_now_be_devigged(conn):
    from vb.market.odds import consensus_fair, latest_quotes
    from vb.repo import upsert_match, upsert_odds

    match_id = upsert_match(conn, "SP1", "2026/27", "2026-08-31T20:00:00",
                            "Barcelona", "Rayo Vallecano", status="scheduled")
    for book, home_price, away_price in (("bet365", 1.95, 1.87),
                                         ("skybet", 1.92, 1.90)):
        upsert_odds(conn, match_id, book, "ah", "home", home_price, -2.75)
        upsert_odds(conn, match_id, book, "ah", "away", away_price, -2.75)

    fair = consensus_fair(latest_quotes(conn, match_id, "ah", -2.75))
    assert set(fair) == {"home", "away"}, "both sides must be in one market"
    assert sum(fair.values()) == pytest.approx(1.0)


def test_an_old_database_has_its_handicap_lines_repaired(tmp_path):
    """Rows written under the old convention are flipped once, and only once."""
    from vb.db import repair_ah_lines, session
    from vb.repo import upsert_match, upsert_odds

    path = tmp_path / "old.db"
    with session(path) as conn:
        match_id = upsert_match(conn, "E0", "2026/27", "2026-08-29T15:00:00",
                                "Liverpool", "Everton", status="scheduled")
        conn.execute("DELETE FROM kv WHERE key = 'fix.ah_line_convention'")
        upsert_odds(conn, match_id, "bet365", "ah", "home", 1.90, -1.0)
        conn.execute("UPDATE odds SET line = 1.0 WHERE selection = 'home'")
        upsert_odds(conn, match_id, "bet365", "ah", "away", 1.90, 1.0)
        conn.execute("DELETE FROM kv WHERE key = 'fix.ah_line_convention'")
        assert repair_ah_lines(conn) == 1
        away = conn.execute(
            "SELECT line FROM odds WHERE selection = 'away'").fetchone()["line"]
        assert away == pytest.approx(-1.0)
        assert repair_ah_lines(conn) == 0, "running twice would undo the repair"
