"""Correcting the model's over-confidence against its own record.

A model that says 55% and delivers 45% will find value everywhere and have
none, because every edge it reports is inflated by the same error. Two seasons
of walk-forward betting measured exactly that: 179 winners expected, 155
delivered, in every probability band at once.

The correction is a straight line through the log-odds — the standard
recalibration for this — fitted on what the model said against what happened:

    corrected_logit = slope x predicted_logit + intercept

A slope near 1 with a negative intercept means the model is not mis-shaped,
just uniformly too confident, and that is what the data shows.

Two cautions worth keeping in view. The fit is drawn from bets the engine
*chose*, which are exactly the ones where its error ran in the flattering
direction, so it corrects the selection as much as the model. And a correction
fitted and tested on the same seasons will always look good: `vb calibrate`
splits the record in half and reports the untouched half, which is the only
number worth reading.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass

WINNING = ("won", "half_won")


def logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def inverse_logit(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def apply(prob: float, slope: float, intercept: float) -> float:
    """Map a raw model probability onto its corrected one."""
    if slope == 1.0 and intercept == 0.0:
        return prob
    return inverse_logit(slope * logit(prob) + intercept)


@dataclass
class Fit:
    slope: float = 1.0
    intercept: float = 0.0
    bets: int = 0

    @property
    def is_identity(self) -> bool:
        return abs(self.slope - 1) < 1e-9 and abs(self.intercept) < 1e-9


def fit(rows: list[tuple[float, bool]], buckets: int = 6) -> Fit:
    """Least squares on the log-odds, one point per bucket, weighted by size.

    Bucketing rather than fitting each bet individually is deliberate: a single
    bet's outcome is 0 or 1, whose log-odds is infinite. The bucket average is
    the observable quantity.
    """
    usable = [(p, won) for p, won in rows if p is not None and 0 < p < 1]
    if len(usable) < 20:
        return Fit(bets=len(usable))

    usable.sort(key=lambda pair: pair[0])
    size = max(1, len(usable) // buckets)
    points: list[tuple[float, float, int]] = []
    for start in range(0, len(usable), size):
        chunk = usable[start:start + size]
        if len(chunk) < 5:
            continue
        predicted = sum(p for p, _ in chunk) / len(chunk)
        actual = sum(1 for _, won in chunk if won) / len(chunk)
        # A bucket nobody won, or everybody won, has no finite log-odds. Nudge
        # it inside the boundary by half a result rather than discarding it.
        actual = min(max(actual, 0.5 / len(chunk)), 1 - 0.5 / len(chunk))
        points.append((predicted, actual, len(chunk)))

    if len(points) < 2:
        return Fit(bets=len(usable))

    weight = sum(n for _, _, n in points)
    mean_x = sum(logit(p) * n for p, _, n in points) / weight
    mean_y = sum(logit(a) * n for _, a, n in points) / weight
    sxy = sum(n * (logit(p) - mean_x) * (logit(a) - mean_y) for p, a, n in points)
    sxx = sum(n * (logit(p) - mean_x) ** 2 for p, _, n in points)
    if sxx <= 0:
        return Fit(bets=len(usable))
    slope = sxy / sxx
    return Fit(slope=slope, intercept=mean_y - slope * mean_x, bets=len(usable))


def settled_bets(conn: sqlite3.Connection) -> list[tuple[str, float, bool]]:
    """(date, what the model said, did it land) for every graded bet."""
    rows = conn.execute(
        "SELECT event_date, model_prob, status FROM bets "
        "WHERE status NOT IN ('pending', 'void') AND model_prob IS NOT NULL "
        "ORDER BY event_date, id").fetchall()
    return [(r["event_date"], float(r["model_prob"]), r["status"] in WINNING)
            for r in rows]


def gap(rows: list[tuple[float, bool]]) -> tuple[float, float, float]:
    """Wins expected, wins seen, and how many standard errors apart they are."""
    expected = sum(p for p, _ in rows)
    actual = sum(1 for _, won in rows if won)
    variance = sum(p * (1 - p) for p, _ in rows)
    z = (expected - actual) / math.sqrt(variance) if variance > 0 else 0.0
    return expected, float(actual), z
