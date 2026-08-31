"""Reviewing the fifteen you already own.

Grades every pick against its projection, works out the strongest legal
starting XI and bench order, ranks captaincy by appetite for risk, and
raises the flags that cost managers points: injuries, suspensions, players
a booking away from a ban, and money sitting idle on the bench.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import rules
from ..model import GameState, Pick, Squad
from .fixtures import FixtureModel, TeamOutlook
from .projection import PlayerProjection, ProjectionModel


@dataclass
class PickReview:
    pick: Pick
    projection: PlayerProjection
    outlook: TeamOutlook
    flags: list[str] = field(default_factory=list)
    verdict: str = "Keep"

    @property
    def player(self):
        return self.pick.player

    @property
    def score(self) -> float:
        return self.projection.total

    @property
    def is_problem(self) -> bool:
        return self.verdict in ("Sell", "Watch")


@dataclass
class CaptainOption:
    player_name: str
    team: str
    projection: float
    ownership: float
    fixtures: str
    rationale: str
    tier: str


@dataclass
class SquadReview:
    squad: Squad
    reviews: list[PickReview]
    best_xi: list[PickReview]
    bench_order: list[PickReview]
    formation: str
    captains: list[CaptainOption]
    warnings: list[str]
    projected_next_gw: float
    projected_horizon: float
    bench_value: float

    def by_position(self, position: int) -> list[PickReview]:
        return [r for r in self.reviews if r.player.position == position]

    @property
    def weakest(self) -> list[PickReview]:
        return sorted(self.reviews, key=lambda r: r.score)[:5]


class SquadAnalyser:
    def __init__(
        self,
        state: GameState,
        fixture_model: FixtureModel,
        projection_model: ProjectionModel,
        horizon: int = 5,
    ) -> None:
        self.state = state
        self.fixtures = fixture_model
        self.projections = projection_model
        self.horizon = horizon

    # -- individual picks -------------------------------------------------

    def review_pick(self, pick: Pick, start_gw: int) -> PickReview:
        player = pick.player
        outlook = self.fixtures.outlook(player.team_id, start_gw, self.horizon)
        projection = self.projections.project(player, outlook.fixtures)
        review = PickReview(pick=pick, projection=projection, outlook=outlook)

        flags: list[str] = []
        if player.status == "i":
            flags.append(f"Injured — {player.news or 'no return date given'}")
        elif player.status == "s":
            flags.append(f"Suspended — {player.news or 'serving a ban'}")
        elif player.status in ("u", "n"):
            flags.append(f"Unavailable — {player.news or 'not in contention'}")
        elif player.status == "d":
            chance = player.chance_next
            flags.append(
                f"Doubtful — {int(chance)}% chance of playing" if chance is not None
                else f"Doubtful — {player.news or 'fitness in question'}"
            )

        # A booking away from a one-match ban.
        if player.yellow_cards >= rules.YELLOWS_FOR_BAN - 1 and start_gw <= rules.YELLOW_BAN_CUTOFF_GW:
            flags.append(
                f"{int(player.yellow_cards)} yellows — one more before GW"
                f"{rules.YELLOW_BAN_CUTOFF_GW} means a ban"
            )

        if projection.expected_minutes < 45 and player.available:
            flags.append("Rotation risk — under 45 minutes expected")

        if outlook.blanks:
            flags.append(f"Blank in GW{', GW'.join(str(g) for g in outlook.blanks)}")
        if outlook.doubles:
            flags.append(f"Double in GW{', GW'.join(str(g) for g in outlook.doubles)}")

        if player.cost_change <= -2:
            flags.append(f"Price falling — down £{abs(player.cost_change)/10:.1f}m this season")

        review.flags = flags
        review.verdict = self._verdict(review)
        return review

    def _verdict(self, review: PickReview) -> str:
        player = review.player
        if not player.available:
            return "Sell"
        if review.projection.expected_minutes < 30:
            return "Sell"

        per_match = review.projection.per_match
        if per_match >= 5.0:
            return "Keep"
        if per_match >= 3.5:
            return "Hold"
        if player.status == "d":
            return "Watch"
        return "Watch" if per_match >= 2.5 else "Sell"

    # -- team selection ---------------------------------------------------

    def pick_best_xi(self, reviews: list[PickReview]) -> tuple[list[PickReview], list[PickReview], str]:
        """Strongest legal XI, then the bench in the order it should be used."""
        by_position: dict[int, list[PickReview]] = {}
        for review in reviews:
            by_position.setdefault(review.player.position, []).append(review)
        for group in by_position.values():
            group.sort(key=lambda r: r.score, reverse=True)

        best: tuple[float, list[PickReview], str] = (-1.0, [], "")
        keepers = by_position.get(1, [])
        if not keepers:
            return reviews[:11], reviews[11:], "unknown"

        for defenders in range(rules.XI_MIN[2], rules.XI_MAX[2] + 1):
            for midfielders in range(rules.XI_MIN[3], rules.XI_MAX[3] + 1):
                forwards = rules.XI_SIZE - 1 - defenders - midfielders
                if not rules.XI_MIN[4] <= forwards <= rules.XI_MAX[4]:
                    continue
                if (
                    len(by_position.get(2, [])) < defenders
                    or len(by_position.get(3, [])) < midfielders
                    or len(by_position.get(4, [])) < forwards
                ):
                    continue
                xi = (
                    keepers[:1]
                    + by_position.get(2, [])[:defenders]
                    + by_position.get(3, [])[:midfielders]
                    + by_position.get(4, [])[:forwards]
                )
                total = sum(r.score for r in xi)
                if total > best[0]:
                    best = (total, xi, f"{defenders}-{midfielders}-{forwards}")

        _, xi, formation = best
        chosen = {id(r) for r in xi}
        bench = [r for r in reviews if id(r) not in chosen]
        # Outfield bench in projection order, reserve keeper last.
        bench.sort(key=lambda r: (r.player.position == 1, -r.score))
        return xi, bench, formation

    # -- captaincy --------------------------------------------------------

    def captain_options(self, xi: list[PickReview]) -> list[CaptainOption]:
        """Three captains: the safe pick, the balanced one, and the punt."""
        # Goalkeepers are legal captains and almost never correct ones: their
        # ceiling is a clean sheet and a handful of saves, with no route to a
        # double-figure haul. Outfield players only.
        candidates = sorted(
            (r for r in xi if r.player.position != 1),
            key=lambda r: r.projection.per_match,
            reverse=True,
        )[:8]
        if not candidates:
            return []

        options: list[CaptainOption] = []
        chosen: set[int] = set()

        def describe(review: PickReview) -> str:
            return ", ".join(f.label for f in review.projection.fixtures[:3]) or "no fixture"

        # Balanced first: the highest projection in the XI, whoever that is.
        # The other two tiers are defined relative to it, so computing it
        # first stops the "safe" pick from outscoring the "balanced" one.
        balanced = candidates[0]
        options.append(
            CaptainOption(
                player_name=balanced.player.name,
                team=self.state.team(balanced.player.team_id).short_name,
                projection=balanced.projection.per_match,
                ownership=balanced.player.selected_by,
                fixtures=describe(balanced),
                tier="Balanced",
                rationale=(
                    f"The highest projected score in your XI at "
                    f"{balanced.projection.per_match:.1f} a match."
                ),
            )
        )
        chosen.add(balanced.player.id)

        # Safe: the best of the heavily owned. This is allowed to be the same
        # player as the balanced pick - when the standout option is also the
        # popular one, saying so is more useful than inventing a difference.
        safe_pool = [
            r for r in candidates
            if r.player.selected_by >= 15 and r.projection.expected_minutes >= 70
        ]
        if safe_pool:
            safe = max(safe_pool, key=lambda r: r.projection.per_match)
            same = safe.player.id == balanced.player.id
            options.insert(
                0,
                CaptainOption(
                    player_name=safe.player.name,
                    team=self.state.team(safe.player.team_id).short_name,
                    projection=safe.projection.per_match,
                    ownership=safe.player.selected_by,
                    fixtures=describe(safe),
                    tier="Safe",
                    rationale=(
                        (
                            "The standout pick is also the popular one, which is the easiest "
                            "captaincy call there is: you take the best projection in your squad "
                            "without handing the field an edge. "
                            if same
                            else ""
                        )
                        + f"Owned by {safe.player.selected_by:.0f}% — captaining him keeps pace "
                        f"with the field. Projected {safe.projection.per_match:.1f} a match."
                    ),
                ),
            )
            chosen.add(safe.player.id)

        # Risky: the best differential the field is not captaining.
        punt_pool = [
            r for r in candidates
            if r.player.selected_by < 15 and r.player.id not in chosen
        ]
        if punt_pool:
            punt = max(punt_pool, key=lambda r: r.projection.per_match)
            options.append(
                CaptainOption(
                    player_name=punt.player.name,
                    team=self.state.team(punt.player.team_id).short_name,
                    projection=punt.projection.per_match,
                    ownership=punt.player.selected_by,
                    fixtures=describe(punt),
                    tier="Risky",
                    rationale=(
                        f"Only {punt.player.selected_by:.1f}% own him. A haul here gains ground on "
                        f"the whole mini-league at once; a blank costs you little that the "
                        f"template will not also suffer."
                    ),
                )
            )
        return options

    # -- the whole squad --------------------------------------------------

    def analyse(self, squad: Squad, start_gw: int) -> SquadReview:
        reviews = [self.review_pick(pick, start_gw) for pick in squad.picks]
        xi, bench, formation = self.pick_best_xi(reviews)

        warnings: list[str] = []
        unavailable = [r for r in reviews if not r.player.available]
        if unavailable:
            warnings.append(
                f"{len(unavailable)} player(s) cannot play: "
                + ", ".join(r.player.name for r in unavailable)
            )

        counts = squad.club_counts()
        for team_id, count in counts.items():
            if count > rules.MAX_PER_CLUB:
                warnings.append(
                    f"{self.state.team(team_id).short_name} has {count} players — over the "
                    f"limit of {rules.MAX_PER_CLUB}"
                )

        bench_value = sum(r.player.price for r in bench)
        if bench_value > 20:
            warnings.append(
                f"£{bench_value:.1f}m is sitting on your bench — that is money not scoring points"
            )

        if squad.bank >= 30:
            warnings.append(
                f"£{squad.bank_m:.1f}m idle in the bank. Unspent money wins nothing."
            )

        # The XI's score for the coming gameweek specifically, and across the
        # whole horizon. Conflating the two badly overstates a single week.
        next_gw_total = sum(r.projection.per_gameweek.get(start_gw, 0.0) for r in xi)
        horizon_total = sum(r.score for r in xi)
        captain = max(
            (r for r in xi if r.player.position != 1),
            key=lambda r: r.projection.per_match,
            default=None,
        )
        if captain:
            next_gw_total += captain.projection.per_gameweek.get(start_gw, 0.0)
            horizon_total += captain.projection.total

        return SquadReview(
            squad=squad,
            reviews=reviews,
            best_xi=xi,
            bench_order=bench,
            formation=formation,
            captains=self.captain_options(xi),
            warnings=warnings,
            projected_next_gw=round(next_gw_total, 1),
            projected_horizon=round(horizon_total, 1),
            bench_value=round(bench_value, 1),
        )
