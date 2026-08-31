"""Projecting points from underlying data.

Past points tell you what a player did; underlying numbers tell you what he
is likely to do next. This module builds an expected-points figure per
gameweek out of expected goals and assists, opponent-adjusted clean sheet
odds, defensive-contribution rates under the 2026/27 thresholds, save
volume and bonus-point tendency - then adjusts the lot for how likely the
player is to actually be on the pitch.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .. import rules
from ..model import Player
from .fixtures import FixtureView, LEAGUE_GOALS_PER_TEAM


def poisson_at_least(k: int, mean: float) -> float:
    """P(X >= k) for a Poisson variable, used for thresholds and clean sheets."""
    if mean <= 0:
        return 0.0
    if k <= 0:
        return 1.0
    cumulative = 0.0
    term = math.exp(-mean)
    for i in range(k):
        if i > 0:
            term *= mean / i
        cumulative += term
    return max(0.0, min(1.0, 1.0 - cumulative))


@dataclass
class PointsBreakdown:
    """Where a projected score is expected to come from."""

    appearance: float = 0.0
    goals: float = 0.0
    assists: float = 0.0
    clean_sheet: float = 0.0
    defcon: float = 0.0
    saves: float = 0.0
    bonus: float = 0.0
    concede_penalty: float = 0.0
    cards: float = 0.0

    @property
    def total(self) -> float:
        return round(
            self.appearance
            + self.goals
            + self.assists
            + self.clean_sheet
            + self.defcon
            + self.saves
            + self.bonus
            + self.concede_penalty
            + self.cards,
            2,
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "Appearance": round(self.appearance, 2),
            "Goals": round(self.goals, 2),
            "Assists": round(self.assists, 2),
            "Clean sheet": round(self.clean_sheet, 2),
            "DefCon": round(self.defcon, 2),
            "Saves": round(self.saves, 2),
            "Bonus": round(self.bonus, 2),
            "Conceded": round(self.concede_penalty, 2),
            "Cards": round(self.cards, 2),
        }


@dataclass
class PlayerProjection:
    player: Player
    per_gameweek: dict[int, float] = field(default_factory=dict)
    breakdown: PointsBreakdown = field(default_factory=PointsBreakdown)
    expected_minutes: float = 0.0
    defcon_chance: float = 0.0
    clean_sheet_chance: float = 0.0
    fixtures: list[FixtureView] = field(default_factory=list)

    @property
    def total(self) -> float:
        return round(sum(self.per_gameweek.values()), 2)

    @property
    def per_match(self) -> float:
        matches = len(self.fixtures) or 1
        return round(self.total / matches, 2)

    @property
    def value(self) -> float:
        """Projected points per million spent - the efficiency of a pick."""
        return round(self.total / max(self.player.price, 0.1), 2)


class ProjectionModel:
    """Turns a player plus a run of fixtures into projected points."""

    def __init__(self, minutes_floor: float = 0.15) -> None:
        self.minutes_floor = minutes_floor

    # -- availability -----------------------------------------------------

    def expected_minutes(self, player: Player) -> float:
        """Minutes we expect in the next match, allowing for fitness news."""
        if player.status in rules.UNAVAILABLE_STATUSES:
            return 0.0

        if player.matches_played > 0:
            base = player.minutes / player.matches_played
        else:
            base = 60.0 if player.cost >= 60 else 30.0

        # A flagged player is scaled by the club's own stated likelihood.
        if player.chance_next is not None:
            base *= player.chance_next / 100.0
        elif player.status == "d":
            base *= 0.6

        return max(0.0, min(90.0, base))

    def start_probability(self, player: Player) -> float:
        minutes = self.expected_minutes(player)
        return max(0.0, min(1.0, minutes / 78.0))

    # -- defensive contributions -----------------------------------------

    def defcon_probability(self, player: Player, minutes: float) -> float:
        """Chance of clearing the DefCon threshold in a match.

        Where per-match history has been loaded we trust the observed hit
        rate; otherwise we model defensive actions as a Poisson process at
        the player's per-90 rate, scaled to the minutes we expect him to play.
        """
        if player.position not in rules.DEFCON_ELIGIBLE:
            return 0.0

        threshold = rules.DEFCON_THRESHOLD.get(player.position, 12)

        if player.matches_played >= 3 and player.matches_hitting_defcon > 0:
            observed = player.matches_hitting_defcon / player.matches_played
            modelled = poisson_at_least(threshold, player.defcon90 * (minutes / 90.0))
            # Blend: observation is truthful but noisy this early in a season.
            return max(0.0, min(1.0, 0.6 * observed + 0.4 * modelled))

        expected_actions = player.defcon90 * (minutes / 90.0)
        return poisson_at_least(threshold, expected_actions)

    # -- the projection ---------------------------------------------------

    def project_match(self, player: Player, fixture: FixtureView) -> PointsBreakdown:
        breakdown = PointsBreakdown()
        minutes = self.expected_minutes(player)
        if minutes <= 0:
            return breakdown

        share = minutes / 90.0
        play_chance = min(1.0, minutes / 20.0)
        sixty_chance = self.start_probability(player)

        # Appearance points
        breakdown.appearance = (
            sixty_chance * rules.APPEARANCE_60_POINTS
            + max(0.0, play_chance - sixty_chance) * rules.APPEARANCE_SUB_POINTS
        )

        # Attacking returns, scaled by how good this fixture looks for the
        # club's attack relative to an average Premier League afternoon.
        attack_multiplier = fixture.expected_goals_for / LEAGUE_GOALS_PER_TEAM
        attack_multiplier = max(0.35, min(2.2, attack_multiplier))

        expected_goals = player.xg90 * share * attack_multiplier
        expected_assists = player.xa90 * share * attack_multiplier
        breakdown.goals = expected_goals * rules.GOAL_POINTS.get(player.position, 5)
        breakdown.assists = expected_assists * rules.ASSIST_POINTS

        # Clean sheets. Blend the fixture model with the player's own
        # expected goals conceded, which captures how exposed his side is.
        cs_points = rules.CLEAN_SHEET_POINTS.get(player.position, 0)
        if cs_points:
            fixture_cs = fixture.clean_sheet_chance
            if player.xgc90 > 0:
                personal_cs = math.exp(-player.xgc90)
                clean_sheet = 0.6 * fixture_cs + 0.4 * personal_cs
            else:
                clean_sheet = fixture_cs
            breakdown.clean_sheet = clean_sheet * cs_points * sixty_chance

        # Goals conceded cost one point per two, for keepers and defenders.
        if player.position in (1, 2):
            conceded = fixture.expected_goals_against * share
            breakdown.concede_penalty = -(conceded / rules.GOALS_CONCEDED_PER_MINUS)

        # Defensive contribution points
        chance = self.defcon_probability(player, minutes)
        breakdown.defcon = chance * rules.DEFCON_POINTS

        # Saves, for keepers only
        if player.position == 1 and player.minutes > 0:
            saves90 = player.saves / (player.minutes / 90.0)
            # Busier keepers face more shots against weaker sides' opponents.
            shot_multiplier = max(0.5, min(2.0, fixture.expected_goals_against / LEAGUE_GOALS_PER_TEAM))
            breakdown.saves = (saves90 * share * shot_multiplier) / rules.SAVES_PER_POINT

        # Bonus, from the player's own rate of earning it
        if player.minutes > 0:
            bonus90 = player.bonus / (player.minutes / 90.0)
            breakdown.bonus = bonus90 * share * min(1.4, max(0.6, attack_multiplier))

        # Cards
        if player.minutes > 0:
            yellows90 = player.yellow_cards / (player.minutes / 90.0)
            breakdown.cards = yellows90 * share * rules.YELLOW_CARD_POINTS

        return breakdown

    def project(
        self,
        player: Player,
        fixtures: list[FixtureView],
    ) -> PlayerProjection:
        """Project a player across a run of fixtures, doubles included."""
        projection = PlayerProjection(player=player, fixtures=list(fixtures))
        projection.expected_minutes = self.expected_minutes(player)
        projection.defcon_chance = self.defcon_probability(player, projection.expected_minutes)

        totals = PointsBreakdown()
        clean_sheet_chances: list[float] = []

        for fixture in fixtures:
            breakdown = self.project_match(player, fixture)
            # A double gameweek adds both fixtures into the same gameweek total.
            projection.per_gameweek[fixture.gameweek] = round(
                projection.per_gameweek.get(fixture.gameweek, 0.0) + breakdown.total, 2
            )
            totals.appearance += breakdown.appearance
            totals.goals += breakdown.goals
            totals.assists += breakdown.assists
            totals.clean_sheet += breakdown.clean_sheet
            totals.defcon += breakdown.defcon
            totals.saves += breakdown.saves
            totals.bonus += breakdown.bonus
            totals.concede_penalty += breakdown.concede_penalty
            totals.cards += breakdown.cards
            clean_sheet_chances.append(fixture.clean_sheet_chance)

        projection.breakdown = totals
        projection.clean_sheet_chance = (
            sum(clean_sheet_chances) / len(clean_sheet_chances) if clean_sheet_chances else 0.0
        )
        return projection
