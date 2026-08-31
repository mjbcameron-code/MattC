"""Grading. A ledger is only worth keeping if the losers go in accurately."""

import pytest

from vb.track.settle import _grade_handicap, grade_leg, leg_multiplier


class FakeMatch(dict):
    """Stands in for a sqlite3.Row."""

    def __getitem__(self, key):
        return dict.get(self, key)

    def keys(self):
        return dict.keys(self)


@pytest.fixture
def home_win_2_1():
    return FakeMatch(status="played", fthg=2, ftag=1, hc=7, ac=4, hy=2, ay=3, hr=0, ar=1)


@pytest.mark.parametrize("market,selection,line,expected", [
    ("h2h", "home", None, "won"),
    ("h2h", "draw", None, "lost"),
    ("h2h", "away", None, "lost"),
    ("totals", "over", 2.5, "won"),
    ("totals", "under", 2.5, "lost"),
    ("totals", "over", 3.5, "lost"),
    ("btts", "yes", None, "won"),
    ("btts", "no", None, "lost"),
    ("double_chance", "1x", None, "won"),
    ("double_chance", "x2", None, "lost"),
    ("dnb", "home", None, "won"),
    ("ah", "home", -0.5, "won"),
    ("ah", "home", -1.0, "void"),
    ("ah", "home", -1.5, "lost"),
    # `line` is the handicap on the home team, so an away punter giving the
    # home side a goal is line +1.0, and receiving one is line -1.0.
    ("ah", "away", -1.0, "void"),      # home won by exactly one
    ("ah", "away", -1.5, "won"),
    ("ah", "away", 1.0, "lost"),
    ("team_totals", "home_over", 1.5, "won"),
    ("team_totals", "away_over", 1.5, "lost"),
    ("correct_score", "2-1", None, "won"),
    ("correct_score", "1-1", None, "lost"),
    ("clean_sheet", "home", None, "lost"),
    ("corners", "over", 10.5, "won"),
    ("corners", "under", 10.5, "lost"),
    ("corners", "home_over", 6.5, "won"),
    ("cards", "over", 4.5, "won"),           # 5 yellows + a red
    ("booking_points", "over", 45.5, "won"),  # 50 + 25 = 75
    ("booking_points", "over", 85.5, "lost"),
])
def test_grading(home_win_2_1, market, selection, line, expected):
    assert grade_leg(home_win_2_1, market, selection, line) == expected


def test_an_unplayed_match_is_not_graded():
    assert grade_leg(FakeMatch(status="scheduled", fthg=None), "h2h", "home", None) is None


def test_player_markets_wait_for_a_human():
    """No free feed carries player match data, so these must not be guessed at."""
    match = FakeMatch(status="played", fthg=1, ftag=0)
    assert grade_leg(match, "player_sot", "over", 0.5, subject="A Player") is None


def test_exact_goal_line_is_a_push():
    match = FakeMatch(status="played", fthg=1, ftag=1)
    assert grade_leg(match, "totals", "over", 2.0) == "void"


@pytest.mark.parametrize("line,expected", [
    (-0.75, "half_won"),   # one leg wins, the other pushes
    (-1.25, "half_lost"),  # one leg pushes, the other loses
    (-0.25, "won"),        # both legs win
    (-1.75, "lost"),
])
def test_quarter_lines_split_the_stake(line, expected):
    assert _grade_handicap(1, line) == expected


def test_multipliers_pay_out_correctly():
    assert leg_multiplier("won", 2.5) == 2.5
    assert leg_multiplier("lost", 2.5) == 0.0
    assert leg_multiplier("void", 2.5) == 1.0
    assert leg_multiplier("half_won", 2.5) == 1.75   # half at 2.5, half returned
    assert leg_multiplier("half_lost", 2.5) == 0.5   # half lost, half returned


def test_closing_line_value_is_measured_against_books_you_could_use(conn):
    """A benchmark the bet was never eligible to reach is not a benchmark.

    "market_max" is the maximum of the whole panel by construction, so it beats
    every individual book's close automatically, and an exchange carries a
    fraction of a sportsbook's margin. Leave either in and closing line value is
    negative before a single bet is struck.
    """
    from vb.repo import upsert_match, upsert_odds
    from vb.track.settle import closing_price

    match_id = upsert_match(conn, league_code="E0", season="2025/26",
                            kickoff="2026-01-10T15:00:00", home="Arsenal",
                            away="Chelsea", status="played")
    for book, price in (("bet365_close", 2.10), ("skybet_close", 2.15),
                        ("betfair_ex_close", 2.32), ("market_max_close", 2.40)):
        upsert_odds(conn, match_id, book, "h2h", "home", price, None,
                    taken_at="2026-01-10", is_closing=True)

    assert closing_price(conn, match_id, "h2h", "home", None) == 2.15, \
        "the exchange and the panel maximum must not set the benchmark"


def test_the_closing_benchmark_falls_back_to_a_real_book(conn):
    from vb.repo import upsert_match, upsert_odds
    from vb.track.settle import closing_price

    match_id = upsert_match(conn, league_code="E0", season="2025/26",
                            kickoff="2026-01-10T15:00:00", home="Spurs",
                            away="Everton", status="played")
    # No closing rows at all — only pre-match prices, one of them unbettable.
    upsert_odds(conn, match_id, "market_max", "h2h", "home", 3.00, None,
                taken_at="2026-01-09")
    upsert_odds(conn, match_id, "bet365", "h2h", "home", 2.80, None,
                taken_at="2026-01-09")
    assert closing_price(conn, match_id, "h2h", "home", None) == 2.80
