"""Joint match simulation, for bet builders and same-game combinations.

Multiplying leg probabilities together is fine across different matches and
badly wrong within one. "Home win" and "over 2.5 goals" are positively linked
(a favourite winning usually means goals); "home win" and "under 2.5" are
negatively linked; corners rise with attacking dominance; cards rise in tight,
scrappy games and fall in comfortable ones.

So a builder is priced by simulating the whole match — goals, corners, cards
and individual players together — and counting how often every leg lands at
once. The correlation falls out of shared latent factors:

* a **tempo** shock, shared by both sides, that opens or closes the game up;
* a **team intensity** shock per side, which drives its goals, shots and corners;
* a **friction** factor for cards, higher when the game stays close.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from .counts import RED_POINTS, YELLOW_POINTS

DEFAULT_SIMS = 40_000


@dataclass
class Leg:
    """One leg of a bet, in the same vocabulary the odds tables use."""

    market: str
    selection: str
    line: float | None = None
    subject: str | None = None        # player name, for player markets
    price: float | None = None
    description: str = ""

    def label(self) -> str:
        if self.description:
            return self.description
        parts = [self.subject] if self.subject else []
        parts.append(self.market)
        parts.append(self.selection)
        if self.line is not None:
            parts.append(str(self.line))
        return " ".join(str(p) for p in parts)


@dataclass
class SimulatedMatch:
    """The outcome of N simulated playings of one fixture."""

    home_goals: np.ndarray
    away_goals: np.ndarray
    home_corners: np.ndarray
    away_corners: np.ndarray
    home_cards: np.ndarray
    away_cards: np.ndarray
    home_reds: np.ndarray
    away_reds: np.ndarray
    player_sot: dict[str, np.ndarray] = field(default_factory=dict)
    player_shots: dict[str, np.ndarray] = field(default_factory=dict)
    player_cards: dict[str, np.ndarray] = field(default_factory=dict)
    player_goals: dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.home_goals)

    @property
    def total_goals(self) -> np.ndarray:
        return self.home_goals + self.away_goals

    @property
    def total_corners(self) -> np.ndarray:
        return self.home_corners + self.away_corners

    @property
    def total_cards(self) -> np.ndarray:
        return self.home_cards + self.away_cards

    @property
    def booking_points(self) -> np.ndarray:
        return (self.total_cards * YELLOW_POINTS
                + (self.home_reds + self.away_reds) * RED_POINTS)

    # -- leg evaluation ----------------------------------------------------
    def hits(self, leg: Leg) -> np.ndarray:
        """Boolean array: did this leg land, in each simulated match?"""
        market, selection = leg.market.lower(), leg.selection.lower()
        line = leg.line
        diff = self.home_goals - self.away_goals

        if market == "h2h":
            return {"home": diff > 0, "draw": diff == 0, "away": diff < 0}[selection]
        if market == "double_chance":
            return {"1x": diff >= 0, "12": diff != 0, "x2": diff <= 0}[selection]
        if market == "dnb":
            return (diff > 0) if selection == "home" else (diff < 0)
        if market == "totals" and line is not None:
            return self.total_goals > line if selection == "over" else self.total_goals < line
        if market == "btts":
            both = (self.home_goals > 0) & (self.away_goals > 0)
            return both if selection == "yes" else ~both
        if market == "team_totals" and line is not None:
            side, _, direction = selection.partition("_")
            goals = self.home_goals if side == "home" else self.away_goals
            return goals > line if direction != "under" else goals < line
        if market == "ah" and line is not None:
            # `line` is the handicap on the home team; the away side mirrors it.
            margin = diff if selection == "home" else -diff
            return (margin + (line if selection == "home" else -line)) > 0
        if market == "correct_score":
            home_goals, away_goals = (int(x) for x in selection.split("-"))
            return (self.home_goals == home_goals) & (self.away_goals == away_goals)
        if market == "clean_sheet":
            return self.away_goals == 0 if selection == "home" else self.home_goals == 0
        if market == "corners" and line is not None:
            if selection in ("over", "under"):
                return self.total_corners > line if selection == "over" \
                    else self.total_corners < line
            side, _, direction = selection.partition("_")
            corners = self.home_corners if side == "home" else self.away_corners
            return corners > line if direction != "under" else corners < line
        if market == "corners":
            if selection == "home":
                return self.home_corners > self.away_corners
            if selection == "away":
                return self.away_corners > self.home_corners
            return self.home_corners == self.away_corners
        if market == "cards" and line is not None:
            if selection in ("over", "under"):
                return self.total_cards > line if selection == "over" \
                    else self.total_cards < line
            side, _, direction = selection.partition("_")
            cards = self.home_cards if side == "home" else self.away_cards
            return cards > line if direction != "under" else cards < line
        if market == "booking_points" and line is not None:
            return self.booking_points > line if selection == "over" \
                else self.booking_points < line
        if market in ("player_sot", "player_shots", "player_card", "player_goal"):
            table = {
                "player_sot": self.player_sot,
                "player_shots": self.player_shots,
                "player_card": self.player_cards,
                "player_goal": self.player_goals,
            }[market]
            counts = table.get(leg.subject or "")
            if counts is None:
                raise KeyError(f"player {leg.subject!r} was not simulated")
            threshold = line if line is not None else 0.5
            if market in ("player_card", "player_goal") and line is None:
                threshold = 0.5
            hit = counts > threshold
            return hit if selection in ("over", "yes", "score", "card") else ~hit
        raise ValueError(f"cannot evaluate leg {leg.market}/{leg.selection}")

    def probability(self, legs: Sequence[Leg]) -> float:
        """Joint probability that every leg lands — correlation included."""
        if not legs:
            return 0.0
        mask = np.ones(self.n, dtype=bool)
        for leg in legs:
            mask &= self.hits(leg)
        return float(mask.mean())


def simulate_match(
    lam_home: float,
    lam_away: float,
    corner_home: float | None = None,
    corner_away: float | None = None,
    card_home: float | None = None,
    card_away: float | None = None,
    red_rate: float = 0.08,
    players: dict[str, dict] | None = None,
    n: int = DEFAULT_SIMS,
    tempo_sd: float = 0.16,
    team_sd: float = 0.22,
    corner_beta: float = 0.65,
    card_gamma: float = 0.30,
    seed: int | None = None,
) -> SimulatedMatch:
    """Simulate one fixture ``n`` times with correlated goals, corners and cards.

    ``players`` maps a player's name to his per-match rates, e.g.
    ``{"Isak": {"side": "home", "sot": 1.4, "shots": 3.1, "cards": 0.18,
    "goals": 0.55}}``.
    """
    rng = np.random.default_rng(seed)

    # Shared tempo shock, then a shock per side. Both are log-normal with mean
    # one, so the simulated averages still match the model's expectations.
    tempo = np.exp(rng.normal(-0.5 * tempo_sd ** 2, tempo_sd, n))
    home_shock = tempo * np.exp(rng.normal(-0.5 * team_sd ** 2, team_sd, n))
    away_shock = tempo * np.exp(rng.normal(-0.5 * team_sd ** 2, team_sd, n))

    home_goals = rng.poisson(lam_home * home_shock)
    away_goals = rng.poisson(lam_away * away_shock)

    # Corners track attacking intensity but less than one-for-one.
    corner_home = corner_home if corner_home is not None else 5.2
    corner_away = corner_away if corner_away is not None else 4.6
    home_corners = rng.poisson(corner_home * (1 + corner_beta * (home_shock - 1)).clip(0.2))
    away_corners = rng.poisson(corner_away * (1 + corner_beta * (away_shock - 1)).clip(0.2))

    # Cards rise in tight games: friction is highest when the margin is small.
    margin = np.abs(home_goals - away_goals)
    friction = 1.0 + card_gamma * (1.0 - np.clip(margin, 0, 3) / 3.0) - card_gamma / 2
    card_home = card_home if card_home is not None else 1.9
    card_away = card_away if card_away is not None else 2.1
    home_cards = rng.poisson(card_home * friction)
    away_cards = rng.poisson(card_away * friction)
    home_reds = rng.poisson(red_rate / 2 * friction)
    away_reds = rng.poisson(red_rate / 2 * friction)

    sim = SimulatedMatch(
        home_goals=home_goals, away_goals=away_goals,
        home_corners=home_corners, away_corners=away_corners,
        home_cards=home_cards, away_cards=away_cards,
        home_reds=home_reds, away_reds=away_reds,
    )

    for name, rates in (players or {}).items():
        shock = home_shock if rates.get("side", "home") == "home" else away_shock
        friction_side = friction
        if rates.get("sot"):
            sim.player_sot[name] = rng.poisson(rates["sot"] * shock)
        if rates.get("shots"):
            sim.player_shots[name] = rng.poisson(rates["shots"] * shock)
        if rates.get("cards"):
            sim.player_cards[name] = rng.poisson(rates["cards"] * friction_side)
        if rates.get("goals"):
            sim.player_goals[name] = rng.poisson(rates["goals"] * shock)
    return sim


def builder_probability(sim: SimulatedMatch, legs: Sequence[Leg]) -> tuple[float, float]:
    """Return (simulated joint probability, naive product of the leg probabilities).

    The gap between the two is the correlation the bookmaker is pricing — or
    failing to price.
    """
    joint = sim.probability(legs)
    naive = 1.0
    for leg in legs:
        naive *= float(sim.hits(leg).mean())
    return joint, naive


def correlation_factor(sim: SimulatedMatch, legs: Sequence[Leg]) -> float:
    """How much more (or less) likely the legs are together than independently."""
    joint, naive = builder_probability(sim, legs)
    if naive <= 1e-9:
        return 1.0
    return joint / naive


def combined_probability(
    sim: SimulatedMatch,
    legs: Sequence[Leg],
    marginals: Sequence[float],
) -> float:
    """Joint probability of same-game legs, from exact marginals plus simulated correlation.

    The simulator deliberately carries more spread than a plain Poisson — real
    scorelines are overdispersed — which nudges its single-leg frequencies a
    point or two away from the analytic model. Taking only the *ratio* from the
    simulation and applying it to the analytic marginals keeps a leg priced the
    same whether it is bet singly or inside a builder, while still capturing the
    correlation between legs, which is the thing a naive product gets wrong.
    """
    if not legs:
        return 0.0
    product = 1.0
    for m in marginals:
        product *= max(0.0, min(1.0, m))
    combined = product * correlation_factor(sim, legs)
    # A joint event can never be likelier than its least likely component.
    return float(min(combined, min(marginals), 1.0)) if marginals else 0.0
