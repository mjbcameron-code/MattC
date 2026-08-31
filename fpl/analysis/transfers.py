"""Finding transfers worth making.

Every available player is projected over the same horizon as your own
squad, which makes the comparison honest: a move is only worth making if
the incoming player beats the outgoing one by more than the hit costs.
Suggestions are graded by how much risk they carry, because a manager
chasing a mini-league needs different advice to one protecting a rank.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import rules
from ..model import GameState, Player, Squad
from .fixtures import FixtureModel
from .projection import PlayerProjection, ProjectionModel
from .squad import SquadReview

# Ownership bands that define the risk tiers.
TEMPLATE_OWNERSHIP = 20.0
DIFFERENTIAL_OWNERSHIP = 8.0


@dataclass
class Candidate:
    player: Player
    projection: PlayerProjection
    team: str

    @property
    def price(self) -> float:
        return self.player.price

    @property
    def ownership(self) -> float:
        return self.player.selected_by

    @property
    def score(self) -> float:
        return self.projection.total

    @property
    def tier(self) -> str:
        if self.ownership >= TEMPLATE_OWNERSHIP:
            return "Safe"
        if self.ownership >= DIFFERENTIAL_OWNERSHIP:
            return "Balanced"
        return "Risky"

    def reasons(self) -> list[str]:
        """Plain-English evidence for why this player is being suggested."""
        player = self.player
        notes: list[str] = []
        if player.xgi90 >= 0.55:
            notes.append(f"{player.xgi90:.2f} expected goal involvements per 90")
        elif player.xgi90 >= 0.35:
            notes.append(f"{player.xgi90:.2f} xGI/90 — steady underlying threat")
        if self.projection.defcon_chance >= 0.5:
            notes.append(
                f"{self.projection.defcon_chance*100:.0f}% chance of DefCon points each match"
            )
        if player.on_pens:
            notes.append("first-choice penalty taker")
        if player.corners_order == 1 or player.freekicks_order == 1:
            notes.append("on set pieces")
        if self.projection.clean_sheet_chance >= 0.33 and player.position in (1, 2):
            notes.append(f"{self.projection.clean_sheet_chance*100:.0f}% clean sheet odds")
        if player.cost_change >= 3:
            notes.append(f"price rising — up £{player.cost_change/10:.1f}m already")
        if self.ownership < DIFFERENTIAL_OWNERSHIP:
            notes.append(f"only {self.ownership:.1f}% owned")
        fixtures = ", ".join(f.label for f in self.projection.fixtures[:4])
        if fixtures:
            notes.append(f"fixtures: {fixtures}")
        return notes


@dataclass
class TransferMove:
    out_player: Player
    in_player: Player
    gain: float
    cost_change: float
    tier: str
    reasons: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        direction = "frees" if self.cost_change < 0 else "costs"
        return (
            f"{self.out_player.name} → {self.in_player.name} "
            f"({direction} £{abs(self.cost_change):.1f}m)"
        )


@dataclass
class TransferPlan:
    tier: str
    moves: list[TransferMove]
    hits: int
    net_gain: float
    bank_after: float
    headline: str
    explanation: str

    @property
    def hit_cost(self) -> int:
        return self.hits * rules.HIT_COST


class TransferAdvisor:
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
        self._cache: dict[int, PlayerProjection] = {}

    # -- projections over the whole player pool ---------------------------

    def project_player(self, player: Player, start_gw: int) -> PlayerProjection:
        if player.id in self._cache:
            return self._cache[player.id]
        outlook = self.fixtures.outlook(player.team_id, start_gw, self.horizon)
        projection = self.projections.project(player, outlook.fixtures)
        self._cache[player.id] = projection
        return projection

    def build_pool(self, start_gw: int, min_minutes: float = 60.0) -> list[Candidate]:
        """Every plausible player, projected and ready to compare."""
        pool: list[Candidate] = []
        for player in self.state.players.values():
            if not player.available:
                continue
            # Ignore players with no evidence of a role yet, unless they are
            # expensive enough that the game itself expects them to start.
            if player.minutes < min_minutes and player.cost < 60:
                continue
            projection = self.project_player(player, start_gw)
            if projection.expected_minutes < 30:
                continue
            pool.append(
                Candidate(
                    player=player,
                    projection=projection,
                    team=self.state.team(player.team_id).short_name,
                )
            )
        pool.sort(key=lambda c: c.score, reverse=True)
        return pool

    def best_by_position(
        self, pool: list[Candidate], position: int, max_price: float, limit: int = 12
    ) -> list[Candidate]:
        return [
            c for c in pool
            if c.player.position == position and c.price <= max_price + 1e-9
        ][:limit]

    def differentials(self, pool: list[Candidate], limit: int = 12) -> list[Candidate]:
        """Strong projections the field has largely missed."""
        picks = [
            c for c in pool
            if c.ownership < DIFFERENTIAL_OWNERSHIP
            and c.projection.per_match >= 3.5
            and c.projection.expected_minutes >= 60
        ]
        picks.sort(key=lambda c: (c.projection.per_match, -c.ownership), reverse=True)
        return picks[:limit]

    def template_gaps(self, squad: Squad, pool: list[Candidate], limit: int = 8) -> list[Candidate]:
        """Heavily owned players you do not have — the risk you are already running."""
        owned = {p.id for p in squad.players}
        gaps = [
            c for c in pool
            if c.player.id not in owned and c.ownership >= TEMPLATE_OWNERSHIP
        ]
        gaps.sort(key=lambda c: c.ownership, reverse=True)
        return gaps[:limit]

    # -- move generation --------------------------------------------------

    def _legal_club_count(self, squad: Squad, out_player: Player, in_player: Player) -> bool:
        counts = squad.club_counts()
        counts[out_player.team_id] = counts.get(out_player.team_id, 0) - 1
        counts[in_player.team_id] = counts.get(in_player.team_id, 0) + 1
        return counts.get(in_player.team_id, 0) <= rules.MAX_PER_CLUB

    def candidate_moves(
        self,
        squad: Squad,
        review: SquadReview,
        pool: list[Candidate],
    ) -> list[TransferMove]:
        """Every single-transfer swap that improves the squad."""
        owned_ids = {p.id for p in squad.players}
        selling_price = {pick.player.id: pick.selling_price for pick in squad.picks}
        moves: list[TransferMove] = []

        for pick_review in review.reviews:
            out_player = pick_review.player
            out_score = pick_review.projection.total
            budget = (selling_price.get(out_player.id, out_player.cost) + squad.bank) / 10.0

            for candidate in pool:
                incoming = candidate.player
                if incoming.id in owned_ids:
                    continue
                if incoming.position != out_player.position:
                    continue
                if candidate.price > budget + 1e-9:
                    continue
                if not self._legal_club_count(squad, out_player, incoming):
                    continue

                gain = candidate.score - out_score
                if gain <= 0.5:
                    continue

                moves.append(
                    TransferMove(
                        out_player=out_player,
                        in_player=incoming,
                        gain=round(gain, 2),
                        cost_change=round(
                            candidate.price - selling_price.get(out_player.id, out_player.cost) / 10.0,
                            1,
                        ),
                        tier=candidate.tier,
                        reasons=candidate.reasons(),
                    )
                )

        moves.sort(key=lambda m: m.gain, reverse=True)
        return moves

    def build_plans(
        self,
        squad: Squad,
        review: SquadReview,
        pool: list[Candidate],
        start_gw: int,
    ) -> list[TransferPlan]:
        """Three plans: play it safe, take a chance, take a risk."""
        moves = self.candidate_moves(squad, review, pool)
        if not moves:
            return []

        free_transfers = max(1, squad.free_transfers)
        plans: list[TransferPlan] = []

        def assemble(pool_moves: list[TransferMove], count: int) -> list[TransferMove]:
            """Take the best moves that do not sell or buy the same player twice."""
            chosen: list[TransferMove] = []
            sold: set[int] = set()
            bought: set[int] = set()
            for move in pool_moves:
                if len(chosen) >= count:
                    break
                if move.out_player.id in sold or move.in_player.id in bought:
                    continue
                chosen.append(move)
                sold.add(move.out_player.id)
                bought.add(move.in_player.id)
            return chosen

        # --- Safe: one transfer, well-owned incoming, no hit.
        safe_moves = [m for m in moves if m.tier == "Safe"] or moves
        safe = assemble(safe_moves, 1)
        if safe:
            plans.append(
                TransferPlan(
                    tier="Safe",
                    moves=safe,
                    hits=0,
                    net_gain=round(sum(m.gain for m in safe), 1),
                    bank_after=round(squad.bank_m - sum(m.cost_change for m in safe), 1),
                    headline=safe[0].summary,
                    explanation=(
                        "One transfer, no hit, and an incoming player enough of the field "
                        "already owns that you are not exposed if he hauls. This is the move "
                        "that cannot really go wrong: you bank the free transfer's value and "
                        "keep your options open for next week."
                    ),
                )
            )

        # --- Balanced: use the free transfers you have, best available gain.
        balanced = assemble(moves, free_transfers)
        if balanced:
            plans.append(
                TransferPlan(
                    tier="Balanced",
                    moves=balanced,
                    hits=0,
                    net_gain=round(sum(m.gain for m in balanced), 1),
                    bank_after=round(squad.bank_m - sum(m.cost_change for m in balanced), 1),
                    headline=" and ".join(m.summary for m in balanced),
                    explanation=(
                        f"Spends {len(balanced)} of your {free_transfers} free transfer(s) on the "
                        "largest projected gain available without paying a hit. Mixes proven "
                        "picks with a little upside — the default plan unless the fixtures or "
                        "your mini-league position argue otherwise."
                    ),
                )
            )

        # --- Risky: differentials, and a hit if the gain justifies it.
        risky_moves = [m for m in moves if m.tier == "Risky"] or moves
        count = min(len(risky_moves), free_transfers + 1)
        risky = assemble(risky_moves, count)
        if risky:
            hits = max(0, len(risky) - free_transfers)
            gross = sum(m.gain for m in risky)
            plans.append(
                TransferPlan(
                    tier="Risky",
                    moves=risky,
                    hits=hits,
                    net_gain=round(gross - hits * rules.HIT_COST, 1),
                    bank_after=round(squad.bank_m - sum(m.cost_change for m in risky), 1),
                    headline=" and ".join(m.summary for m in risky),
                    explanation=(
                        "Brings in players the field has largely ignored"
                        + (
                            f", and pays a {hits * rules.HIT_COST}-point hit to do it. "
                            "The projection still clears the hit, but a hit is only ever worth "
                            "taking if you believe the underlying numbers more than the crowd does. "
                            if hits
                            else ". "
                        )
                        + "In a mini-league this is how you actually gain ground: matching the "
                        "template can only ever hold your position."
                    ),
                )
            )

        return plans
