"""The scout itself: pulls the analysis together into one report.

Short term is this deadline - who starts, who captains, which transfer.
Medium term is the next month of fixtures, where swings are planned before
they arrive. Long term is the shape of the squad and the chip calendar,
which is decided by the Gameweek 19 cut-off rather than by form.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import rules
from .analysis.chips import ChipAdvice, ChipStrategist
from .analysis.fixtures import FixtureModel
from .analysis.projection import ProjectionModel
from .analysis.squad import SquadAnalyser, SquadReview
from .analysis.transfers import Candidate, TransferAdvisor, TransferPlan
from .loader import LoadResult
from .model import GameState, Squad


@dataclass
class StrategyNote:
    horizon: str
    headline: str
    points: list[str] = field(default_factory=list)


@dataclass
class ScoutReport:
    state: GameState
    squad: Squad | None
    gameweek: int
    review: SquadReview | None
    plans: list[TransferPlan]
    chips: list[ChipAdvice]
    differentials: list[Candidate]
    template_gaps: list[Candidate]
    best_by_position: dict[str, list[Candidate]]
    strategy: list[StrategyNote]
    fixture_scan: dict[int, dict]
    horizon: int
    enriched: int
    generated_at: str = ""
    is_sample: bool = False


class Scout:
    def __init__(self, horizon: int = 5, aggression: str = "balanced") -> None:
        self.horizon = horizon
        self.aggression = aggression

    def run(self, loaded: LoadResult) -> ScoutReport:
        from datetime import datetime, timezone

        state = loaded.state
        gameweek = loaded.gameweek
        fixture_model = FixtureModel(state)
        projection_model = ProjectionModel()

        analyser = SquadAnalyser(state, fixture_model, projection_model, self.horizon)
        advisor = TransferAdvisor(state, fixture_model, projection_model, self.horizon)

        review = analyser.analyse(loaded.squad, gameweek) if loaded.squad else None
        pool = advisor.build_pool(gameweek)

        plans: list[TransferPlan] = []
        gaps: list[Candidate] = []
        chips: list[ChipAdvice] = []
        if loaded.squad and review:
            plans = advisor.build_plans(loaded.squad, review, pool, gameweek)
            gaps = advisor.template_gaps(loaded.squad, pool)
            chips = ChipStrategist(state, fixture_model).advise(loaded.squad, review, gameweek)

        best_by_position = {
            rules.POSITIONS[position]: advisor.best_by_position(pool, position, 99.0, 10)
            for position in (1, 2, 3, 4)
        }

        scan = fixture_model.scan_doubles_and_blanks(gameweek, min(38, gameweek + 12))

        return ScoutReport(
            state=state,
            squad=loaded.squad,
            gameweek=gameweek,
            review=review,
            plans=plans,
            chips=chips,
            differentials=advisor.differentials(pool),
            template_gaps=gaps,
            best_by_position=best_by_position,
            strategy=self.build_strategy(state, loaded.squad, review, plans, chips, scan, gameweek),
            fixture_scan=scan,
            horizon=self.horizon,
            enriched=loaded.enriched,
            generated_at=datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC"),
        )

    # -- narrative --------------------------------------------------------

    def build_strategy(
        self,
        state: GameState,
        squad: Squad | None,
        review: SquadReview | None,
        plans: list[TransferPlan],
        chips: list[ChipAdvice],
        scan: dict[int, dict],
        gameweek: int,
    ) -> list[StrategyNote]:
        notes: list[StrategyNote] = []

        # --- Short term ---------------------------------------------------
        short: list[str] = []
        if review:
            captain = review.captains[1] if len(review.captains) > 1 else (
                review.captains[0] if review.captains else None
            )
            if captain:
                short.append(
                    f"Captain {captain.player_name} ({captain.team}) — projected "
                    f"{captain.projection:.1f} a match against {captain.fixtures}."
                )
            short.append(
                f"Play a {review.formation}. Your strongest XI projects "
                f"{review.projected_next_gw:.0f} points in GW{gameweek} including the captain, "
                f"and {review.projected_horizon:.0f} across GW{gameweek}–{gameweek + self.horizon - 1}."
            )
            if review.bench_order:
                short.append(
                    "Bench order: "
                    + " → ".join(r.player.name for r in review.bench_order)
                    + ". Autosubs only fire if a starter records no minutes, so the first "
                    "name here should be the one most likely to play."
                )
            for warning in review.warnings[:3]:
                short.append(warning)
            if plans:
                balanced = next((p for p in plans if p.tier == "Balanced"), plans[0])
                short.append(
                    f"Transfer: {balanced.headline}. Projected gain "
                    f"{balanced.net_gain:+.1f} points over {self.horizon} gameweeks."
                )
        else:
            short.append("Load a team ID to get squad-specific advice for this deadline.")

        notes.append(
            StrategyNote(
                horizon="Short term",
                headline=f"Gameweek {gameweek} — the decisions due at this deadline",
                points=short,
            )
        )

        # --- Medium term --------------------------------------------------
        medium: list[str] = []
        end = gameweek + self.horizon - 1
        medium.append(
            f"The model looks at GW{gameweek}–{end}. Plan transfers across that block rather "
            "than one week at a time: rolling a transfer to make two moves next week is "
            "almost always better than paying a hit this week."
        )
        doubles = [gw for gw, data in scan.items() if data["doubles"]]
        blanks = [gw for gw, data in scan.items() if data["blanks"]]
        if doubles:
            medium.append(
                "Double gameweeks scheduled: "
                + ", ".join(f"GW{gw} ({', '.join(scan[gw]['doubles'][:6])})" for gw in doubles[:3])
                + ". Build towards these — they are where Bench Boost and Triple Captain pay."
            )
        if blanks:
            medium.append(
                "Blank gameweeks scheduled: "
                + ", ".join(f"GW{gw} ({len(scan[gw]['blanks'])} clubs idle)" for gw in blanks[:3])
                + ". A Free Hit covers the worst of these without breaking your squad."
            )
        if not doubles and not blanks:
            medium.append(
                "No doubles or blanks are on the calendar yet. They appear once cup rounds "
                "displace league fixtures, typically from the winter onwards — so keep the "
                "Free Hit and Bench Boost in hand rather than spending them on a normal week."
            )
        if review:
            weak = review.weakest[:3]
            if weak:
                medium.append(
                    "Weakest links to plan out: "
                    + ", ".join(f"{r.player.name} ({r.projection.per_match:.1f}/match)" for r in weak)
                    + "."
                )
        notes.append(
            StrategyNote(
                horizon="Medium term",
                headline=f"GW{gameweek}–{end} — fixture swings and transfer planning",
                points=medium,
            )
        )

        # --- Long term ----------------------------------------------------
        long_term: list[str] = []
        weeks_to_deadline = rules.FIRST_HALF_LAST_GW - gameweek
        if weeks_to_deadline > 0:
            unused = [c.label for c in chips if c.available]
            long_term.append(
                f"{weeks_to_deadline} gameweeks until the first chip set expires at the GW"
                f"{rules.FIRST_HALF_LAST_GW} deadline."
                + (
                    f" Still unplayed: {', '.join(unused)}. Anything left on 2 January is lost — "
                    "a chip played at 80% of its ideal week beats a chip not played at all."
                    if unused
                    else " You have used the first set."
                )
            )
        else:
            long_term.append(
                f"You are in the second half of the season. The second chip set runs to GW"
                f"{rules.TOTAL_GAMEWEEKS} and cannot be rolled over."
            )

        long_term.append(
            "Squad structure matters more than any single transfer. Decide whether you are "
            "running a heavy front three funded by cheap defenders, or spreading value through "
            "midfield. Under the current rules cheap defenders who clear the 10-action DefCon "
            "threshold are the most efficient points in the game — two points a week from a "
            "£4.5m defender is a £9.0m midfielder's return at half the price."
        )
        long_term.append(
            "Team value is a slow compounding advantage. Buying players before a price rise "
            "and holding them adds a fraction of a million each week, which becomes a premium "
            "forward by the spring."
        )
        if self.aggression == "aggressive":
            long_term.append(
                "For a mini-league, rank protection is worthless — only the gap to the people "
                "above you counts. Carry two or three genuine differentials at all times, and "
                "captain differently to your rivals when the projection is close. Matching them "
                "move for move guarantees you finish exactly where you started."
            )

        notes.append(
            StrategyNote(
                horizon="Long term",
                headline="Chip calendar, squad structure and team value",
                points=long_term,
            )
        )
        return notes
