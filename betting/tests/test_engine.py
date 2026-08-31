"""The engine end to end: simulation, selection, and the guard against phantom edges."""

import pytest

from vb.market.odds import latest_quotes
from vb.market.value import scan_fixture
from vb.models.fixture import ModelBank, build_fixture
from vb.models.match import MatchProbs
from vb.models.ratings import fit_league
from vb.models.season import simulate_season
from vb.models.simulate import (Leg, combined_probability, correlation_factor,
                                simulate_match)
from vb.repo import upsert_odds
from vb.sample import generate_league


@pytest.fixture(scope="module")
def sim():
    return simulate_match(1.75, 1.05, 6.1, 4.4, 1.8, 2.2, n=60_000, seed=1)


def test_simulated_means_match_the_inputs(sim):
    assert sim.total_goals.mean() == pytest.approx(2.80, abs=0.06)
    assert sim.total_corners.mean() == pytest.approx(10.5, abs=0.2)


def test_goals_and_a_home_win_are_positively_linked(sim):
    """A favourite winning usually means goals — a builder must price that in."""
    legs = [Leg("h2h", "home"), Leg("totals", "over", 2.5)]
    assert correlation_factor(sim, legs) > 1.05


def test_a_home_win_and_under_25_fight_each_other(sim):
    legs = [Leg("h2h", "home"), Leg("totals", "under", 2.5)]
    assert correlation_factor(sim, legs) < 0.95


def test_cards_rise_in_a_tight_game(sim):
    legs = [Leg("h2h", "draw"), Leg("cards", "over", 3.5)]
    assert correlation_factor(sim, legs) > 1.0


def test_a_one_leg_builder_equals_the_single_price(sim):
    """Legs must not be priced differently inside a builder than on their own."""
    probs = MatchProbs(1.75, 1.05)
    combined = combined_probability(sim, [Leg("h2h", "home")], [probs.home_win])
    assert combined == pytest.approx(probs.home_win)


def test_a_combination_is_never_likelier_than_its_least_likely_leg(sim):
    probs = MatchProbs(1.75, 1.05)
    marginals = [probs.home_win, probs.total_over(2.5), probs.btts]
    legs = [Leg("h2h", "home"), Leg("totals", "over", 2.5), Leg("btts", "yes")]
    assert combined_probability(sim, legs, marginals) <= min(marginals) + 1e-12


# ---------------------------------------------------------------------------
@pytest.fixture
def league(conn):
    """Half a synthetic season of League Two, with one fixture ahead."""
    from datetime import datetime, timedelta

    generate_league(conn, "E3", "2025/26", datetime.now() - timedelta(weeks=30),
                    played_fraction=0.7, seed=5)
    return conn


def test_ratings_recover_the_shape_of_the_league(league):
    model = fit_league(league, "E3")
    assert model is not None
    assert model.n_matches > 100
    assert 0.05 < model.home_adv < 0.6           # a plausible home advantage
    table = model.table()
    assert table[0][3] > table[-1][3]            # someone is better than someone else
    home, away = model.expected_goals(table[0][0], table[-1][0])
    assert home > away                           # the best side at home outscores the worst


def test_fair_prices_produce_no_bets(league):
    """The most important guard in the suite.

    If the book is priced at exactly the model's own probabilities, with no
    margin at all, there is no edge to find. Any bet returned here would be the
    engine inventing value out of its own arithmetic.
    """
    bank = ModelBank(league)
    match = league.execute(
        "SELECT * FROM matches WHERE league_code = 'E3' AND status = 'scheduled' LIMIT 1"
    ).fetchone()
    fixture = build_fixture(league, match, bank, with_players=False)
    league.execute("DELETE FROM odds WHERE match_id = ?", (fixture.match_id,))

    for selection in ("home", "draw", "away"):
        price = 1 / fixture.probs.probability("h2h", selection)
        for book in ("bet365", "skybet", "paddypower"):
            upsert_odds(league, fixture.match_id, book, "h2h", selection, price,
                        taken_at="2020-01-01")
    for selection in ("over", "under"):
        price = 1 / fixture.probs.probability("totals", selection, 2.5)
        for book in ("bet365", "skybet", "paddypower"):
            upsert_odds(league, fixture.match_id, book, "totals", selection, price,
                        2.5, taken_at="2020-01-01")

    assert scan_fixture(league, fixture) == []


def test_a_generous_price_is_found(league):
    """The mirror image: a price well above fair value must be picked up."""
    bank = ModelBank(league)
    match = league.execute(
        "SELECT * FROM matches WHERE league_code = 'E3' AND status = 'scheduled' LIMIT 1"
    ).fetchone()
    fixture = build_fixture(league, match, bank, with_players=False)
    league.execute("DELETE FROM odds WHERE match_id = ?", (fixture.match_id,))

    for selection in ("home", "draw", "away"):
        fair = 1 / fixture.probs.probability("h2h", selection)
        for book in ("bet365", "skybet", "paddypower"):
            upsert_odds(league, fixture.match_id, book, "h2h", selection, fair,
                        taken_at="2020-01-01")
    # One book goes 15% over the odds on the home side — a real, findable edge.
    home_fair = 1 / fixture.probs.probability("h2h", "home")
    upsert_odds(league, fixture.match_id, "coral", "h2h", "home", home_fair * 1.15,
                taken_at="2020-01-01")
    upsert_odds(league, fixture.match_id, "coral", "h2h", "draw",
                1 / fixture.probs.probability("h2h", "draw"), taken_at="2020-01-01")
    upsert_odds(league, fixture.match_id, "coral", "h2h", "away",
                1 / fixture.probs.probability("h2h", "away"), taken_at="2020-01-01")

    found = scan_fixture(league, fixture)
    assert any(c.selection == "home" and c.bookmaker == "coral" for c in found)
    assert all(c.stake_pts > 0 for c in found)


def test_prices_taken_after_the_decision_are_invisible(league):
    """Backtests must never see a price that did not exist when the bet was made."""
    match = league.execute(
        "SELECT * FROM matches WHERE league_code = 'E3' AND status = 'scheduled' LIMIT 1"
    ).fetchone()
    upsert_odds(league, match["id"], "skybet", "h2h", "home", 3.0,
                taken_at="2030-01-01T12:00:00")
    assert latest_quotes(league, match["id"], "h2h", as_of="2020-01-01") == []
    assert latest_quotes(league, match["id"], "h2h", as_of="2031-01-01")


def test_season_probabilities_are_coherent(league):
    model = fit_league(league, "E3")
    outlook = simulate_season(league, model, "2025/26", simulations=2000, seed=3)
    teams = list(outlook.teams)
    assert sum(outlook.title(t) for t in teams) == pytest.approx(1.0, abs=1e-9)
    assert sum(outlook.probability_position(t, 4) for t in teams) == pytest.approx(4.0, abs=1e-9)
    assert sum(outlook.probability_bottom(t, 3) for t in teams) == pytest.approx(3.0, abs=1e-9)


# ---------------------------------------------------------------------------
def test_form_signals_admit_when_the_run_is_last_season(conn):
    """On opening weekend a club's "last six" are from May. Say so.

    The ratings model already discounts those games by age. The write-up did
    not: it called them recent form, which on matchday one is three months and
    a transfer window out of date.
    """
    from datetime import datetime, timedelta

    from vb.features.form import recent_form
    from vb.repo import upsert_match

    # Six games played last spring, then a long summer.
    for i in range(6):
        upsert_match(conn, "E0", "2025/26",
                     (datetime(2026, 4, 1) + timedelta(days=7 * i)).isoformat(),
                     "Alpha FC", f"Rival {i}", fthg=2, ftag=0)
    team_id = conn.execute("SELECT id FROM teams WHERE name = 'Alpha'").fetchone()["id"]

    august = recent_form(conn, team_id, "E0", datetime(2026, 8, 29))
    assert august.is_stale
    assert august.current_season_games == 0
    assert "last season" in august.run_phrase()

    # The same run, read the week after it happened, is simply form.
    may = recent_form(conn, team_id, "E0", datetime(2026, 5, 12))
    assert not may.is_stale
    assert may.run_phrase() == f"their last {may.played}"


def test_an_implausible_edge_is_treated_as_a_fault_not_a_windfall(league):
    """A 60% edge on a market a dozen books price is a bug, not value.

    Left in, it goes straight to the top of the card at maximum stake, which is
    the worst possible outcome for a number that came from a mis-read line or a
    one-sided book.
    """
    bank = ModelBank(league)
    match = league.execute(
        "SELECT * FROM matches WHERE league_code = 'E3' AND status = 'scheduled' LIMIT 1"
    ).fetchone()
    fixture = build_fixture(league, match, bank, with_players=False)
    league.execute("DELETE FROM odds WHERE match_id = ?", (fixture.match_id,))
    for selection in ("home", "draw", "away"):
        fair = 1 / fixture.probs.probability("h2h", selection)
        for book in ("bet365", "skybet", "paddypower"):
            upsert_odds(league, fixture.match_id, book, "h2h", selection, fair,
                        taken_at="2020-01-01")
    home_fair = 1 / fixture.probs.probability("h2h", "home")
    upsert_odds(league, fixture.match_id, "coral", "h2h", "home", home_fair * 1.6,
                taken_at="2020-01-01")
    assert not [c for c in scan_fixture(league, fixture) if c.bookmaker == "coral"]


def test_an_exchange_price_is_never_the_recommendation(league):
    """Exchanges set the benchmark; they are not the bet.

    Their margin is a fraction of a sportsbook's, so an exchange is almost
    always the best price on the board — and it is also weighted as the sharp
    reference when fair value is calculated. Recommending one measures a price
    against itself and reports the difference as value.
    """
    bank = ModelBank(league)
    match = league.execute(
        "SELECT * FROM matches WHERE league_code = 'E3' AND status = 'scheduled' "
        "LIMIT 1 OFFSET 1").fetchone()
    fixture = build_fixture(league, match, bank, with_players=False)
    league.execute("DELETE FROM odds WHERE match_id = ?", (fixture.match_id,))
    for selection in ("home", "draw", "away"):
        fair = 1 / fixture.probs.probability("h2h", selection)
        upsert_odds(league, fixture.match_id, "bet365", "h2h", selection, fair * 0.97,
                    taken_at="2020-01-01")
        # The exchange is the best price on every selection, as it usually is.
        upsert_odds(league, fixture.match_id, "matchbook", "h2h", selection,
                    fair * 1.08, taken_at="2020-01-01")
    found = scan_fixture(league, fixture)
    assert not [c for c in found if c.bookmaker == "matchbook"]
