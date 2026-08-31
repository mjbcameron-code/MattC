"""Chip strategy.

2026/27 gives two sets of four chips - Wildcard, Free Hit, Triple Captain,
Bench Boost - and the first set dies at the Gameweek 19 deadline. Chips left
unplayed in the first half are simply lost, so the calendar matters as much
as the fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import rules
from ..model import Squad
from .fixtures import FixtureModel
from .squad import SquadReview


@dataclass
class ChipAdvice:
    chip: str
    label: str
    half: str
    available: bool
    recommended_gw: int | None
    urgency: str          # "Hold", "Plan", "Use soon", "Expiring"
    rationale: str
    confidence: str = "Medium"


class ChipStrategist:
    def __init__(self, state, fixture_model: FixtureModel) -> None:
        self.state = state
        self.fixtures = fixture_model

    def remaining(self, squad: Squad, current_gw: int) -> dict[str, bool]:
        """Which chips from the relevant set are still in hand."""
        half = "first" if current_gw <= rules.FIRST_HALF_LAST_GW else "second"
        used_this_half = set()
        for entry in squad.chips_used:
            # chips_used carries (name, gameweek) pairs where available.
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                name, gameweek = entry
                in_first = int(gameweek) <= rules.FIRST_HALF_LAST_GW
                if (half == "first") == in_first:
                    used_this_half.add(str(name))
            else:
                used_this_half.add(str(entry))
        return {chip: chip not in used_this_half for chip in rules.CHIP_NAMES}

    def advise(
        self,
        squad: Squad,
        review: SquadReview,
        current_gw: int,
        horizon_end: int = 38,
    ) -> list[ChipAdvice]:
        remaining = self.remaining(squad, current_gw)
        half = "First half" if current_gw <= rules.FIRST_HALF_LAST_GW else "Second half"
        deadline_gw = rules.FIRST_HALF_LAST_GW if half == "First half" else rules.TOTAL_GAMEWEEKS
        weeks_left = max(0, deadline_gw - current_gw)

        scan = self.fixtures.scan_doubles_and_blanks(current_gw, min(horizon_end, deadline_gw))
        double_weeks = [gw for gw, data in scan.items() if data["doubles"]]
        blank_weeks = [gw for gw, data in scan.items() if data["blanks"]]

        advice: list[ChipAdvice] = []

        def urgency(target: int | None) -> str:
            if weeks_left <= 3:
                return "Expiring"
            if target is not None and target - current_gw <= 1:
                return "Use soon"
            if target is not None:
                return "Plan"
            return "Hold"

        # --- Bench Boost -------------------------------------------------
        bench_strength = sum(r.projection.per_match for r in review.bench_order)
        bb_target = double_weeks[0] if double_weeks else None
        advice.append(
            ChipAdvice(
                chip="bboost",
                label="Bench Boost",
                half=half,
                available=remaining.get("bboost", True),
                recommended_gw=bb_target,
                urgency=urgency(bb_target),
                confidence="High" if bb_target else "Low",
                rationale=(
                    (
                        f"Your bench currently projects {bench_strength:.1f} points a week. "
                        + (
                            f"GW{bb_target} is a double gameweek — that is where a Bench Boost "
                            f"pays, because all fifteen play twice."
                            if bb_target
                            else "No double gameweek is scheduled yet. Doubles are usually created "
                            "later in the season when cup rounds displace league fixtures, so hold "
                            "the chip and revisit once the calendar firms up."
                        )
                    )
                    + (
                        f" Only {weeks_left} gameweeks remain before this set expires — if no double "
                        "arrives, play it on your best-fixture week rather than losing it."
                        if weeks_left <= 5
                        else ""
                    )
                ),
            )
        )

        # --- Triple Captain ----------------------------------------------
        best_captain = review.captains[0] if review.captains else None
        tc_target = double_weeks[0] if double_weeks else None
        advice.append(
            ChipAdvice(
                chip="3xc",
                label="Triple Captain",
                half=half,
                available=remaining.get("3xc", True),
                recommended_gw=tc_target,
                urgency=urgency(tc_target),
                confidence="High" if tc_target else "Medium",
                rationale=(
                    (
                        f"GW{tc_target} is a double — a premium forward playing twice is the "
                        "textbook Triple Captain."
                        if tc_target
                        else "Save it for a double gameweek, or for a premium with a home fixture "
                        "against a promoted side. "
                    )
                    + (
                        f" Your strongest captain right now is {best_captain.player_name} at "
                        f"{best_captain.projection:.1f} projected."
                        if best_captain
                        else ""
                    )
                ),
            )
        )

        # --- Free Hit ------------------------------------------------------
        fh_target = blank_weeks[0] if blank_weeks else None
        advice.append(
            ChipAdvice(
                chip="freehit",
                label="Free Hit",
                half=half,
                available=remaining.get("freehit", True),
                recommended_gw=fh_target,
                urgency=urgency(fh_target),
                confidence="High" if fh_target else "Low",
                rationale=(
                    f"GW{fh_target} is a blank for several clubs — a Free Hit lets you field "
                    "eleven players who actually have a fixture, then hands your squad back."
                    if fh_target
                    else "Nothing to target yet. The Free Hit is the chip to hold longest: it "
                    "rescues a blank gameweek, or attacks a double without wrecking your squad."
                ),
            )
        )

        # --- Wildcard ------------------------------------------------------
        broken = len([r for r in review.reviews if r.is_problem])
        wc_target = current_gw if broken >= 4 else None
        advice.append(
            ChipAdvice(
                chip="wildcard",
                label="Wildcard",
                half=half,
                available=remaining.get("wildcard", True),
                recommended_gw=wc_target,
                urgency=urgency(wc_target),
                confidence="High" if broken >= 5 else "Medium",
                rationale=(
                    (
                        f"{broken} of your fifteen are flagged as sell-or-watch. Once four or more "
                        "players need replacing, transfers alone cannot fix the squad without "
                        "paying repeated hits — that is the moment a Wildcard is worth more than "
                        "the points it saves."
                        if broken >= 4
                        else f"Only {broken} player(s) genuinely need moving. A Wildcard is wasted "
                        "on a squad that two free transfers can repair. Hold it for a fixture "
                        "swing or an injury crisis."
                    )
                    + (
                        f" Be aware: {weeks_left} gameweeks until the first-set deadline at GW"
                        f"{rules.FIRST_HALF_LAST_GW}. An unplayed first-half chip is simply lost."
                        if half == "First half" and weeks_left <= 6
                        else ""
                    )
                ),
            )
        )

        return advice
