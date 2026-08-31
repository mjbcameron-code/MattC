"""From two expected-goal numbers to a price for every market on the coupon.

Everything downstream — 1X2, over/under any line, both teams to score, Asian
handicaps, correct score, winning margin — is read off one joint distribution
over scorelines, so the numbers are guaranteed to be mutually consistent. That
matters for bet builders: a "Home win & over 2.5" price built from two
independent guesses is wrong, because the two legs are correlated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cached_property

import numpy as np

MAX_GOALS = 12


def poisson_pmf(lam: float, k: np.ndarray | int) -> np.ndarray:
    ks = np.asarray(k, dtype=float)
    return np.exp(-lam + ks * math.log(max(lam, 1e-9)) - _log_factorial(ks))


def _log_factorial(k: np.ndarray) -> np.ndarray:
    from scipy.special import gammaln

    return gammaln(k + 1.0)


def score_matrix(lam_home: float, lam_away: float, rho: float = 0.0,
                 max_goals: int = MAX_GOALS) -> np.ndarray:
    """Joint scoreline probabilities with the Dixon-Coles low-score correction."""
    ks = np.arange(max_goals + 1)
    home = poisson_pmf(lam_home, ks)
    away = poisson_pmf(lam_away, ks)
    matrix = np.outer(home, away)
    if rho:
        matrix[0, 0] *= 1.0 - lam_home * lam_away * rho
        matrix[0, 1] *= 1.0 + lam_home * rho
        matrix[1, 0] *= 1.0 + lam_away * rho
        matrix[1, 1] *= 1.0 - rho
        matrix = np.clip(matrix, 0.0, None)
    total = matrix.sum()
    return matrix / total if total > 0 else matrix


@dataclass
class MatchProbs:
    """Every market for one fixture, derived from the scoreline distribution."""

    lam_home: float
    lam_away: float
    rho: float = 0.0
    max_goals: int = MAX_GOALS

    @cached_property
    def matrix(self) -> np.ndarray:
        return score_matrix(self.lam_home, self.lam_away, self.rho, self.max_goals)

    @cached_property
    def _grid(self) -> tuple[np.ndarray, np.ndarray]:
        ks = np.arange(self.max_goals + 1)
        return np.meshgrid(ks, ks, indexing="ij")

    # -- core markets -------------------------------------------------------
    @cached_property
    def home_win(self) -> float:
        return float(np.tril(self.matrix, -1).sum())

    @cached_property
    def draw(self) -> float:
        return float(np.trace(self.matrix))

    @cached_property
    def away_win(self) -> float:
        return float(np.triu(self.matrix, 1).sum())

    @cached_property
    def btts(self) -> float:
        return float(self.matrix[1:, 1:].sum())

    def total_over(self, line: float) -> float:
        home, away = self._grid
        return float(self.matrix[(home + away) > line].sum())

    def total_under(self, line: float) -> float:
        home, away = self._grid
        return float(self.matrix[(home + away) < line].sum())

    def team_total_over(self, line: float, side: str) -> float:
        home, away = self._grid
        goals = home if side == "home" else away
        return float(self.matrix[goals > line].sum())

    def exact_score(self, home_goals: int, away_goals: int) -> float:
        if home_goals > self.max_goals or away_goals > self.max_goals:
            return 0.0
        return float(self.matrix[home_goals, away_goals])

    def clean_sheet(self, side: str) -> float:
        return float(self.matrix[:, 0].sum()) if side == "home" \
            else float(self.matrix[0, :].sum())

    def winning_margin(self, side: str, margin: int) -> float:
        home, away = self._grid
        diff = home - away
        target = margin if side == "home" else -margin
        return float(self.matrix[diff == target].sum())

    # -- derived combinations ----------------------------------------------
    def double_chance(self, selection: str) -> float:
        return {
            "1X": self.home_win + self.draw,
            "12": self.home_win + self.away_win,
            "X2": self.draw + self.away_win,
        }[selection.upper()]

    def draw_no_bet(self, side: str) -> float:
        """Probability of winning the bet once the draw is refunded."""
        live = self.home_win + self.away_win
        if live <= 0:
            return 0.0
        return (self.home_win if side == "home" else self.away_win) / live

    def asian_handicap(self, line: float, side: str) -> tuple[float, float, float]:
        """Return (win, push, loss) for a handicap applied to ``side``.

        Quarter lines split the stake across the two neighbouring half-lines,
        so their outcome is the average of the two.
        """
        if abs((line * 4) % 2) > 1e-9:      # .25 or .75 — a split line
            lower, upper = line - 0.25, line + 0.25
            a = self.asian_handicap(lower, side)
            b = self.asian_handicap(upper, side)
            return tuple((x + y) / 2 for x, y in zip(a, b))  # type: ignore[return-value]
        home, away = self._grid
        diff = (home - away) if side == "home" else (away - home)
        adjusted = diff + line
        win = float(self.matrix[adjusted > 1e-9].sum())
        push = float(self.matrix[np.abs(adjusted) < 1e-9].sum())
        return win, push, 1.0 - win - push

    def ah_break_even(self, line: float, side: str) -> float:
        """The probability an Asian handicap needs to be a break-even bet.

        A push returns the stake, so it shrinks the effective market rather
        than counting as a loss: this is win / (win + loss).
        """
        win, push, loss = self.asian_handicap(line, side)
        live = win + loss
        return win / live if live > 1e-9 else 0.0

    # -- generic lookup -----------------------------------------------------
    def probability(self, market: str, selection: str, line: float | None = None
                    ) -> float | None:
        """Look a market up by name — the interface the value engine speaks."""
        market, selection = market.lower(), selection.lower()
        if market == "h2h":
            return {"home": self.home_win, "draw": self.draw,
                    "away": self.away_win}.get(selection)
        if market == "totals" and line is not None:
            if selection == "over":
                return self.total_over(line)
            if selection == "under":
                return self.total_under(line)
        if market == "team_totals" and line is not None:
            side, _, over_under = selection.partition("_")
            if side in ("home", "away"):
                p = self.team_total_over(line, side)
                return p if over_under != "under" else 1 - p
        if market == "btts":
            return self.btts if selection == "yes" else 1 - self.btts
        if market == "double_chance":
            try:
                return self.double_chance(selection)
            except KeyError:
                return None
        if market == "dnb":
            return self.draw_no_bet(selection)
        if market == "ah" and line is not None:
            # Stored lines are always from the home team's point of view, so
            # both sides of a market share one line and can be devigged as a
            # pair. The away side takes the mirror image.
            return self.ah_break_even(line if selection == "home" else -line,
                                      selection)
        if market == "correct_score":
            try:
                home_goals, away_goals = (int(x) for x in selection.split("-"))
            except ValueError:
                return None
            return self.exact_score(home_goals, away_goals)
        if market == "clean_sheet":
            return self.clean_sheet(selection)
        return None

    def summary(self) -> dict[str, float]:
        return {
            "xG home": round(self.lam_home, 2),
            "xG away": round(self.lam_away, 2),
            "home win": round(self.home_win, 3),
            "draw": round(self.draw, 3),
            "away win": round(self.away_win, 3),
            "over 2.5": round(self.total_over(2.5), 3),
            "btts": round(self.btts, 3),
        }
