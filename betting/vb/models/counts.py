"""Corners and cards: a shared attack/defence rate model with overdispersion.

Both markets work the same way. Every club has a rate at which it *generates*
the event and a rate at which it *concedes* it, and the expectation for a
fixture is the league average scaled by both:

    expected = league_average × team_generation × opponent_concession

Counts are then turned into over/under prices with a negative binomial rather
than a Poisson, because real corner and card totals are noticeably more spread
out than a Poisson allows — using a Poisson here systematically overprices the
middle lines and underprices the ends, which is precisely where these markets
are bet.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from scipy.stats import nbinom

# A yellow is 10 points, a red 25 — the standard bookmaker booking-points scale.
YELLOW_POINTS = 10
RED_POINTS = 25


@dataclass
class RateModel:
    """Per-team generation/concession multipliers for one countable event."""

    league_code: str
    kind: str                                  # "corners" | "cards"
    league_home: float                         # league mean, home side
    league_away: float                         # league mean, away side
    generate: dict[int, float] = field(default_factory=dict)
    concede: dict[int, float] = field(default_factory=dict)
    dispersion: float = 0.0                    # negative binomial r for the total
    red_rate: float = 0.0                      # reds per match, both sides
    n_matches: int = 0

    def expected(self, home_id: int, away_id: int,
                 neutral: bool = False) -> tuple[float, float]:
        home_base = (self.league_home + self.league_away) / 2 if neutral else self.league_home
        away_base = (self.league_home + self.league_away) / 2 if neutral else self.league_away
        home = home_base * self.generate.get(home_id, 1.0) * self.concede.get(away_id, 1.0)
        away = away_base * self.generate.get(away_id, 1.0) * self.concede.get(home_id, 1.0)
        return max(0.2, home), max(0.2, away)


def _shrunk_ratio(total: float, exposure: float, prior_games: float) -> float:
    """Team rate relative to league average, pulled toward 1.0 on small samples."""
    if exposure <= 0:
        return 1.0
    return (total + prior_games) / (exposure + prior_games)


def fit_rates(
    conn: sqlite3.Connection,
    league_code: str,
    kind: str,
    as_of: datetime | None = None,
    half_life: float = 240.0,
    prior_games: float = 6.0,
) -> RateModel | None:
    """Fit generation/concession multipliers for corners or cards."""
    as_of = as_of or datetime.now()
    if kind == "corners":
        rows = conn.execute(
            "SELECT kickoff, home_id, away_id, hc AS h, ac AS a, 0 AS reds "
            "FROM matches WHERE league_code = ? AND status = 'played' "
            "AND hc IS NOT NULL AND ac IS NOT NULL AND kickoff < ?",
            (league_code, as_of.isoformat()),
        ).fetchall()
    elif kind == "cards":
        # Yellow *counts*, not booking points: points are lumpy multiples of ten
        # and fit a count distribution badly. Reds are tracked separately and
        # folded back in when a booking-points price is needed.
        rows = conn.execute(
            "SELECT kickoff, home_id, away_id, hy AS h, ay AS a, "
            "(COALESCE(hr,0) + COALESCE(ar,0)) AS reds "
            "FROM matches WHERE league_code = ? AND status = 'played' "
            "AND hy IS NOT NULL AND ay IS NOT NULL AND kickoff < ?",
            (league_code, as_of.isoformat()),
        ).fetchall()
    else:
        raise ValueError(f"unknown kind {kind!r}")

    if len(rows) < 20:
        return None

    xi = math.log(2) / max(1.0, half_life)
    weights, home_vals, away_vals = [], [], []
    for r in rows:
        try:
            days = (as_of - datetime.fromisoformat(r["kickoff"][:19])).days
        except ValueError:
            days = 0
        weights.append(math.exp(-xi * max(0, days)))
        home_vals.append(float(r["h"]))
        away_vals.append(float(r["a"]))

    weights = np.array(weights)
    home_vals = np.array(home_vals)
    away_vals = np.array(away_vals)
    league_home = float(np.average(home_vals, weights=weights))
    league_away = float(np.average(away_vals, weights=weights))

    # Weighted totals per team, split by whether the club made or conceded it.
    made: dict[int, list[float]] = {}
    made_exp: dict[int, list[float]] = {}
    conceded: dict[int, list[float]] = {}
    conceded_exp: dict[int, list[float]] = {}
    for r, w, hv, av in zip(rows, weights, home_vals, away_vals):
        h, a = r["home_id"], r["away_id"]
        made.setdefault(h, []).append(w * hv)
        made_exp.setdefault(h, []).append(w * league_home)
        made.setdefault(a, []).append(w * av)
        made_exp.setdefault(a, []).append(w * league_away)
        conceded.setdefault(a, []).append(w * hv)
        conceded_exp.setdefault(a, []).append(w * league_home)
        conceded.setdefault(h, []).append(w * av)
        conceded_exp.setdefault(h, []).append(w * league_away)

    generate = {
        team: _shrunk_ratio(sum(vals), sum(made_exp[team]),
                            prior_games * (league_home + league_away) / 2)
        for team, vals in made.items()
    }
    concede = {
        team: _shrunk_ratio(sum(vals), sum(conceded_exp[team]),
                            prior_games * (league_home + league_away) / 2)
        for team, vals in conceded.items()
    }

    totals = home_vals + away_vals
    mean, var = float(totals.mean()), float(totals.var(ddof=1))
    dispersion = mean ** 2 / (var - mean) if var > mean * 1.02 else 0.0

    red_rate = float(np.average([float(r["reds"]) for r in rows], weights=weights))

    return RateModel(
        league_code=league_code, kind=kind,
        league_home=league_home, league_away=league_away,
        generate=generate, concede=concede,
        dispersion=float(dispersion), red_rate=red_rate, n_matches=len(rows),
    )


# ---------------------------------------------------------------------------
# turning an expectation into prices
# ---------------------------------------------------------------------------
def over_probability(mean: float, line: float, dispersion: float = 0.0) -> float:
    """P(count > line). Negative binomial when a dispersion estimate exists."""
    threshold = math.floor(line)          # lines are always .5, so no pushes
    if dispersion and dispersion > 0.5 and mean > 0:
        r = dispersion
        p = r / (r + mean)
        return float(1.0 - nbinom.cdf(threshold, r, p))
    # Poisson fallback
    total, term = 0.0, math.exp(-mean)
    for k in range(0, threshold + 1):
        if k:
            term *= mean / k
        total += term
    return max(0.0, 1.0 - total)


def under_probability(mean: float, line: float, dispersion: float = 0.0) -> float:
    return 1.0 - over_probability(mean, line, dispersion)


@dataclass
class CountProbs:
    """Over/under prices for one fixture's corner or card count."""

    home_mean: float
    away_mean: float
    dispersion: float = 0.0

    @property
    def total(self) -> float:
        return self.home_mean + self.away_mean

    def over(self, line: float) -> float:
        return over_probability(self.total, line, self.dispersion)

    def under(self, line: float) -> float:
        return under_probability(self.total, line, self.dispersion)

    def team_over(self, line: float, side: str) -> float:
        mean = self.home_mean if side == "home" else self.away_mean
        # Team-level dispersion scales with the share of the total.
        share = mean / self.total if self.total else 0.5
        return over_probability(mean, line, self.dispersion * share if self.dispersion else 0.0)

    def most(self, side: str) -> float:
        """P(this side has more of them than the other) — 'most corners' market."""
        home = _count_pmf(self.home_mean, self.dispersion / 2 if self.dispersion else 0.0)
        away = _count_pmf(self.away_mean, self.dispersion / 2 if self.dispersion else 0.0)
        joint = np.outer(home, away)
        if side == "home":
            return float(np.tril(joint, -1).sum())
        if side == "away":
            return float(np.triu(joint, 1).sum())
        return float(np.trace(joint))

    def booking_points_over(self, line: float, red_rate: float = 0.0) -> float:
        """P(booking points > line), where a yellow is 10 and a red is 25.

        The yellow-count distribution is convolved with a small Poisson for
        reds, so a line like 45.5 correctly reflects that a red card is worth
        two and a half bookings.
        """
        yellows = _count_pmf(self.total, self.dispersion)
        reds = _count_pmf(max(red_rate, 1e-6), 0.0, max_count=4)
        probability = 0.0
        for y, py in enumerate(yellows):
            if py < 1e-12:
                continue
            for r, pr in enumerate(reds):
                if py * pr < 1e-12:
                    continue
                if y * YELLOW_POINTS + r * RED_POINTS > line:
                    probability += py * pr
        return float(probability)

    def probability(self, market: str, selection: str, line: float | None) -> float | None:
        selection = selection.lower()
        if line is not None:
            if selection == "over":
                return self.over(line)
            if selection == "under":
                return self.under(line)
            if selection.startswith(("home_", "away_")):
                side, _, direction = selection.partition("_")
                p = self.team_over(line, side)
                return p if direction == "over" else 1 - p
        if selection in ("home", "away", "draw"):
            return self.most(selection)
        return None


def _count_pmf(mean: float, dispersion: float, max_count: int = 40) -> np.ndarray:
    """Probability of each count, truncated at ``max_count`` and renormalised.

    Renormalising matters: without it the truncated tail leaks probability and
    the three-way "most corners" market stops summing to one.
    """
    ks = np.arange(max_count + 1)
    if dispersion and dispersion > 0.5 and mean > 0:
        r = dispersion
        p = r / (r + mean)
        pmf = nbinom.pmf(ks, r, p)
    else:
        from .match import poisson_pmf

        pmf = poisson_pmf(mean, ks)
    total = pmf.sum()
    return pmf / total if total > 0 else pmf
