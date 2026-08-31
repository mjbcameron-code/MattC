"""Tests for the FPL scout.

The live API is not reachable from a test run, so everything here works from
the generated sample season, plus hand-built players for the edge cases that
matter: unavailable players, defensive thresholds and hostile input.
"""

from __future__ import annotations

import html
import os
import re
import unittest

from fpl import rules
from fpl.analysis.fixtures import FixtureModel, FixtureView
from fpl.analysis.projection import ProjectionModel, poisson_at_least
from fpl.loader import load_all
from fpl.model import GameState, Player
from fpl.report import render
from fpl.sample import SampleClient
from fpl.scout import Scout


def make_player(**overrides) -> Player:
    base = {
        "id": 1, "web_name": "Test", "team": 1, "element_type": 3,
        "now_cost": 60, "minutes": 270, "starts": 3,
    }
    base.update(overrides)
    player = Player.parse(base)
    player.matches_played = 3
    return player


EASY = FixtureView(4, 2, "OPP", True, 2, 2.30, 0.90)
HARD = FixtureView(4, 2, "OPP", False, 5, 0.90, 2.30)


class TestPoisson(unittest.TestCase):
    def test_bounds(self):
        self.assertEqual(poisson_at_least(0, 5), 1.0)
        self.assertEqual(poisson_at_least(10, 0), 0.0)
        for k, mean in ((10, 10), (12, 8), (5, 3)):
            self.assertTrue(0.0 <= poisson_at_least(k, mean) <= 1.0)

    def test_monotonic_in_rate(self):
        """A busier player is likelier to clear the same threshold."""
        low = poisson_at_least(10, 6)
        high = poisson_at_least(10, 14)
        self.assertLess(low, high)

    def test_monotonic_in_threshold(self):
        self.assertGreater(poisson_at_least(8, 10), poisson_at_least(12, 10))


class TestProjection(unittest.TestCase):
    def setUp(self):
        self.model = ProjectionModel()

    def test_fixture_quality_moves_the_projection(self):
        striker = make_player(element_type=4, expected_goals="2.1", expected_assists="0.6")
        easy = self.model.project(striker, [EASY]).total
        hard = self.model.project(striker, [HARD]).total
        self.assertGreater(easy, hard)

    def test_unavailable_player_projects_nothing(self):
        for status in rules.UNAVAILABLE_STATUSES:
            player = make_player(status=status)
            self.assertEqual(self.model.expected_minutes(player), 0.0)
            self.assertEqual(self.model.project(player, [EASY]).total, 0.0)

    def test_doubt_scales_minutes_down(self):
        fit = make_player()
        doubtful = make_player(status="d", chance_of_playing_next_round=25)
        self.assertLess(
            self.model.expected_minutes(doubtful), self.model.expected_minutes(fit)
        )

    def test_defcon_threshold_differs_by_position(self):
        """A midfielder needs 12 actions where a defender needs 10."""
        defender = make_player(element_type=2, clearances_blocks_interceptions=21, tackles=9)
        midfielder = make_player(element_type=3, clearances_blocks_interceptions=21, tackles=9)
        midfielder.matches_hitting_defcon = 0
        defender.matches_hitting_defcon = 0
        self.assertGreater(
            self.model.defcon_probability(defender, 90),
            self.model.defcon_probability(midfielder, 90),
        )

    def test_keepers_never_earn_defcon(self):
        keeper = make_player(element_type=1, clearances_blocks_interceptions=60, tackles=30)
        self.assertEqual(self.model.defcon_probability(keeper, 90), 0.0)

    def test_double_gameweek_accumulates_into_one_week(self):
        striker = make_player(element_type=4, expected_goals="2.1")
        single = self.model.project(striker, [EASY])
        double = self.model.project(striker, [EASY, EASY])
        self.assertAlmostEqual(
            double.per_gameweek[4], single.per_gameweek[4] * 2, places=1
        )

    def test_breakdown_sums_to_total(self):
        player = make_player(element_type=2, expected_goals="0.4", bonus=4, saves=0)
        projection = self.model.project(player, [EASY, HARD])
        self.assertAlmostEqual(
            projection.breakdown.total, sum(projection.per_gameweek.values()), places=1
        )


class TestFixtureModel(unittest.TestCase):
    def setUp(self):
        bootstrap = {"teams": [
            {"id": 1, "name": "Strong", "short_name": "STR", "strength_attack_home": 1300,
             "strength_attack_away": 1250, "strength_defence_home": 1300,
             "strength_defence_away": 1250},
            {"id": 2, "name": "Weak", "short_name": "WEK", "strength_attack_home": 950,
             "strength_attack_away": 900, "strength_defence_home": 950,
             "strength_defence_away": 900},
        ], "elements": [], "events": []}
        fixtures = [{"id": 1, "event": 4, "team_h": 1, "team_a": 2, "finished": False,
                     "team_h_difficulty": 2, "team_a_difficulty": 5}]
        self.state = GameState.build(bootstrap, fixtures)
        self.model = FixtureModel(self.state)

    def test_ratings_are_mirrored(self):
        strong = self.model.outlook(1, 4, 1).fixtures[0]
        weak = self.model.outlook(2, 4, 1).fixtures[0]
        self.assertAlmostEqual(strong.expected_goals_for, weak.expected_goals_against, places=2)
        self.assertGreater(strong.expected_goals_for, weak.expected_goals_for)

    def test_missing_fixture_counts_as_a_blank(self):
        outlook = self.model.outlook(1, 4, 3)
        self.assertEqual(outlook.blanks, [5, 6])
        self.assertEqual(outlook.match_count, 1)


class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loaded = load_all(SampleClient(), entry_id=1234567, deep=True)
        cls.report = Scout(horizon=5, aggression="aggressive").run(cls.loaded)

    def test_squad_loads_completely(self):
        squad = self.loaded.squad
        self.assertEqual(len(squad.picks), rules.SQUAD_SIZE)
        shape = {}
        for player in squad.players:
            shape[player.position] = shape.get(player.position, 0) + 1
        self.assertEqual(shape, rules.SQUAD_SHAPE)

    def test_club_limit_respected_in_source_squad(self):
        for count in self.loaded.squad.club_counts().values():
            self.assertLessEqual(count, rules.MAX_PER_CLUB)

    def test_best_xi_is_legal(self):
        review = self.report.review
        self.assertEqual(len(review.best_xi), rules.XI_SIZE)
        self.assertEqual(len(review.bench_order), rules.SQUAD_SIZE - rules.XI_SIZE)
        counts = {}
        for item in review.best_xi:
            counts[item.player.position] = counts.get(item.player.position, 0) + 1
        self.assertEqual(counts.get(1), 1, "exactly one goalkeeper must start")
        for position, minimum in rules.XI_MIN.items():
            self.assertGreaterEqual(counts.get(position, 0), minimum)
            self.assertLessEqual(counts.get(position, 0), rules.XI_MAX[position])

    def test_xi_and_bench_partition_the_squad(self):
        review = self.report.review
        ids = [item.player.id for item in review.best_xi + review.bench_order]
        self.assertEqual(sorted(ids), sorted(p.id for p in self.loaded.squad.players))

    def test_captain_is_never_a_goalkeeper(self):
        names = {c.player_name for c in self.report.review.captains}
        keepers = {
            p.name for p in self.loaded.squad.players if p.position == 1
        }
        self.assertFalse(names & keepers)

    def test_safe_captain_never_outscores_balanced(self):
        by_tier = {c.tier: c for c in self.report.review.captains}
        if "Safe" in by_tier and "Balanced" in by_tier:
            self.assertLessEqual(
                by_tier["Safe"].projection, by_tier["Balanced"].projection + 1e-9
            )

    def test_risky_captain_is_a_genuine_differential(self):
        by_tier = {c.tier: c for c in self.report.review.captains}
        if "Risky" in by_tier:
            self.assertLess(by_tier["Risky"].ownership, 15.0)

    def test_transfer_plans_stay_within_budget(self):
        squad = self.loaded.squad
        selling = {p.player.id: p.selling_price for p in squad.picks}
        for plan in self.report.plans:
            spend = sum(
                move.in_player.cost - selling.get(move.out_player.id, move.out_player.cost)
                for move in plan.moves
            )
            self.assertLessEqual(
                spend, squad.bank + 1e-6,
                f"{plan.tier} plan spends more than the bank allows",
            )

    def test_transfers_keep_positions_and_club_limits(self):
        squad = self.loaded.squad
        for plan in self.report.plans:
            counts = squad.club_counts()
            for move in plan.moves:
                self.assertEqual(move.out_player.position, move.in_player.position)
                counts[move.out_player.team_id] -= 1
                counts[move.in_player.team_id] = counts.get(move.in_player.team_id, 0) + 1
            for club, count in counts.items():
                self.assertLessEqual(count, rules.MAX_PER_CLUB)

    def test_no_plan_sells_or_buys_the_same_player_twice(self):
        for plan in self.report.plans:
            out_ids = [m.out_player.id for m in plan.moves]
            in_ids = [m.in_player.id for m in plan.moves]
            self.assertEqual(len(out_ids), len(set(out_ids)))
            self.assertEqual(len(in_ids), len(set(in_ids)))
            self.assertFalse(set(out_ids) & set(in_ids))

    def test_hits_are_deducted_from_the_net_gain(self):
        for plan in self.report.plans:
            gross = sum(m.gain for m in plan.moves)
            self.assertAlmostEqual(
                plan.net_gain, gross - plan.hits * rules.HIT_COST, places=1
            )

    def test_doubles_and_blanks_are_found(self):
        scan = self.report.fixture_scan
        self.assertIn(10, scan, "the sample season has a double in GW10")
        self.assertTrue(scan[10]["doubles"])
        self.assertIn(8, scan, "the sample season has a blank in GW8")
        self.assertTrue(scan[8]["blanks"])

    def test_strategy_covers_all_three_horizons(self):
        horizons = [note.horizon for note in self.report.strategy]
        self.assertEqual(horizons, ["Short term", "Medium term", "Long term"])
        for note in self.report.strategy:
            self.assertTrue(note.points, f"{note.horizon} has no advice")

    def test_projection_horizon_exceeds_single_gameweek(self):
        review = self.report.review
        self.assertGreater(review.projected_horizon, review.projected_next_gw)


class TestReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loaded = load_all(SampleClient(), entry_id=1234567, deep=False)
        cls.html = render(Scout(horizon=5).run(loaded))

    def test_is_self_contained(self):
        external = set(re.findall(r'(?:src|href)="(https?://[^"]+)"', self.html))
        for url in external:
            self.assertTrue(
                url.startswith("https://fonts.g"),
                f"unexpected external dependency: {url}",
            )

    def test_every_panel_is_present(self):
        for key in ("squad", "transfers", "strategy", "watchlist", "fixtures", "method"):
            self.assertIn(f'id="panel-{key}"', self.html)

    def test_tags_are_balanced(self):
        import html.parser

        void = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                "link", "meta", "source", "track", "wbr"}

        class Checker(html.parser.HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack = []
                self.errors = []

            def handle_starttag(self, tag, attrs):
                if tag not in void:
                    self.stack.append(tag)

            def handle_endtag(self, tag):
                if tag in void:
                    return
                if not self.stack or self.stack[-1] != tag:
                    self.errors.append(tag)
                    if tag in self.stack:
                        while self.stack and self.stack.pop() != tag:
                            pass
                else:
                    self.stack.pop()

        checker = Checker()
        checker.feed(self.html)
        self.assertEqual(checker.errors, [])
        self.assertEqual(checker.stack, [])

    def test_dark_theme_tokens_have_light_definitions(self):
        """No colour may be defined only inside a dark-theme block."""
        from fpl.report import CSS

        root_block = CSS.split("@media")[0]
        root_tokens = set(re.findall(r"(--[a-z0-9-]+)\s*:", root_block))
        dark_block = CSS[CSS.index("@media (prefers-color-scheme"):]
        dark_tokens = set(re.findall(r"(--[a-z0-9-]+)\s*:", dark_block))
        self.assertEqual(dark_tokens - root_tokens, set())

    def test_all_referenced_tokens_are_defined(self):
        from fpl.report import CSS

        used = set(re.findall(r"var\((--[a-z0-9-]+)\)", CSS))
        defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", CSS))
        self.assertEqual(used - defined, set())

    def test_hostile_player_names_are_escaped(self):
        """A player name is API data, so it must never reach the page as markup."""
        client = SampleClient()
        client._bootstrap["elements"][0]["web_name"] = '<script>alert("x")</script>'
        loaded = load_all(client, entry_id=1234567, deep=False)
        page = render(Scout(horizon=3).run(loaded))
        self.assertNotIn('<script>alert("x")</script>', page)
        self.assertIn("&lt;script&gt;", page)


class TestConfig(unittest.TestCase):
    """The team ID is remembered so it only has to be typed once."""

    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._env = dict(os.environ)
        os.environ["FPL_SCOUT_CONFIG_DIR"] = self.tmp.name
        os.environ.pop("FPL_TEAM_ID", None)
        import importlib

        import fpl.config
        self.config = importlib.reload(fpl.config)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        import importlib

        import fpl.config
        importlib.reload(fpl.config)

    def test_nothing_remembered_at_first(self):
        self.assertIsNone(self.config.load_team_id())

    def test_round_trip(self):
        self.config.save_team_id(12642)
        self.assertEqual(self.config.load_team_id(), 12642)

    def test_environment_wins_over_stored_value(self):
        self.config.save_team_id(12642)
        os.environ["FPL_TEAM_ID"] = "999"
        self.assertEqual(self.config.load_team_id(), 999)

    def test_junk_values_are_ignored(self):
        os.environ["FPL_TEAM_ID"] = "not-a-number"
        self.assertIsNone(self.config.load_team_id())
        self.config.CONFIG_FILE.write_text("{ broken json")
        self.assertIsNone(self.config.load_team_id())

    def test_a_uuid_is_not_accepted_as_a_team_id(self):
        os.environ["FPL_TEAM_ID"] = "fb191bf6-7c65-4bf3-8f75-e666cb93fcd9"
        self.assertIsNone(self.config.load_team_id())

    def test_saving_is_never_fatal(self):
        os.environ["FPL_SCOUT_CONFIG_DIR"] = "/proc/nonexistent/nope"
        import importlib

        import fpl.config
        config = importlib.reload(fpl.config)
        self.assertIsNone(config.save_team_id(1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
