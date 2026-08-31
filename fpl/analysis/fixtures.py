"""Fixture modelling: difficulty, congestion, doubles and blanks.

FPL ships its own 1-5 difficulty rating, but it is coarse and set before a
ball is kicked. We rate each fixture twice instead - once for what it means
to a club's attackers, once for what it means to its defence - using the
team strength ratings the API exposes, which move with form.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..model import Fixture, GameState

# Long-run Premier League scoring rate, used as the baseline both sides of
# a fixture regress towards.
LEAGUE_GOALS_PER_TEAM = 1.45
HOME_ADVANTAGE = 1.10


@dataclass
class FixtureView:
    """One fixture, seen from one club's point of view."""

    gameweek: int
    opponent_id: int
    opponent: str
    home: bool
    difficulty: int
    expected_goals_for: float
    expected_goals_against: float

    @property
    def label(self) -> str:
        return f"{self.opponent}{'(H)' if self.home else '(A)'}"

    @property
    def clean_sheet_chance(self) -> float:
        """Poisson probability the opponent fails to score."""
        return math.exp(-self.expected_goals_against)


@dataclass
class TeamOutlook:
    team_id: int
    short_name: str
    fixtures: list[FixtureView]
    doubles: list[int]
    blanks: list[int]

    @property
    def attack_score(self) -> float:
        """Mean expected goals for, across the horizon."""
        if not self.fixtures:
            return 0.0
        return sum(f.expected_goals_for for f in self.fixtures) / len(self.fixtures)

    @property
    def defence_score(self) -> float:
        if not self.fixtures:
            return 0.0
        return sum(f.clean_sheet_chance for f in self.fixtures) / len(self.fixtures)

    @property
    def mean_difficulty(self) -> float:
        if not self.fixtures:
            return 3.0
        return sum(f.difficulty for f in self.fixtures) / len(self.fixtures)

    @property
    def match_count(self) -> int:
        return len(self.fixtures)


class FixtureModel:
    """Rates every upcoming fixture for every club."""

    def __init__(self, state: GameState) -> None:
        self.state = state
        teams = list(state.teams.values())
        self.avg_attack = self._mean([(t.attack_home + t.attack_away) / 2 for t in teams], 1100.0)
        self.avg_defence = self._mean([(t.defence_home + t.defence_away) / 2 for t in teams], 1100.0)

    @staticmethod
    def _mean(values: list[float], fallback: float) -> float:
        usable = [v for v in values if v > 0]
        return sum(usable) / len(usable) if usable else fallback

    def rate(self, team_id: int, fixture: Fixture) -> FixtureView:
        home = fixture.is_home(team_id)
        opponent_id = fixture.opponent_of(team_id) or 0
        us = self.state.team(team_id)
        them = self.state.team(opponent_id)

        attack = us.attack(home) / self.avg_attack if self.avg_attack else 1.0
        their_defence = them.defence(not home) / self.avg_defence if self.avg_defence else 1.0
        their_attack = them.attack(not home) / self.avg_attack if self.avg_attack else 1.0
        our_defence = us.defence(home) / self.avg_defence if self.avg_defence else 1.0

        # A stronger defensive rating means harder to score against, so it
        # divides the opponent's expected goals rather than multiplying them.
        goals_for = LEAGUE_GOALS_PER_TEAM * attack / max(their_defence, 0.4)
        goals_against = LEAGUE_GOALS_PER_TEAM * their_attack / max(our_defence, 0.4)
        if home:
            goals_for *= HOME_ADVANTAGE
            goals_against /= HOME_ADVANTAGE
        else:
            goals_against *= HOME_ADVANTAGE
            goals_for /= HOME_ADVANTAGE

        return FixtureView(
            gameweek=fixture.event or 0,
            opponent_id=opponent_id,
            opponent=them.short_name,
            home=home,
            difficulty=fixture.difficulty_for(team_id),
            expected_goals_for=round(max(0.15, min(goals_for, 4.5)), 3),
            expected_goals_against=round(max(0.15, min(goals_against, 4.5)), 3),
        )

    def outlook(self, team_id: int, start_gw: int, horizon: int) -> TeamOutlook:
        """How the next `horizon` gameweeks look for one club."""
        window = range(start_gw, start_gw + horizon)
        views: list[FixtureView] = []
        doubles: list[int] = []
        blanks: list[int] = []

        for gameweek in window:
            matches = [f for f in self.state.fixtures_for(team_id, gameweek) if not f.finished]
            if len(matches) == 0:
                blanks.append(gameweek)
            elif len(matches) > 1:
                doubles.append(gameweek)
            views.extend(self.rate(team_id, fixture) for fixture in matches)

        return TeamOutlook(
            team_id=team_id,
            short_name=self.state.team(team_id).short_name,
            fixtures=views,
            doubles=doubles,
            blanks=blanks,
        )

    def all_outlooks(self, start_gw: int, horizon: int) -> dict[int, TeamOutlook]:
        return {
            team_id: self.outlook(team_id, start_gw, horizon)
            for team_id in self.state.teams
        }

    def scan_doubles_and_blanks(self, start_gw: int, until_gw: int) -> dict[int, dict]:
        """Find gameweeks where clubs play twice or not at all.

        Doubles and blanks are usually created later in the season as cup
        rounds displace league fixtures, so an empty result early on is the
        expected answer rather than a failure.
        """
        report: dict[int, dict] = {}
        for gameweek in range(start_gw, until_gw + 1):
            doubling: list[str] = []
            blanking: list[str] = []
            for team_id, team in self.state.teams.items():
                matches = [f for f in self.state.fixtures_for(team_id, gameweek) if not f.finished]
                if len(matches) > 1:
                    doubling.append(team.short_name)
                elif not matches:
                    blanking.append(team.short_name)
            if doubling or blanking:
                report[gameweek] = {"doubles": sorted(doubling), "blanks": sorted(blanking)}
        return report
