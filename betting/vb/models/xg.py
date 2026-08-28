"""Expected goals — real where a feed exists, inferred from shots where it doesn't.

understat publishes xG for the Premier League, Bundesliga, Serie A and La Liga.
It publishes nothing for League Two or the Scottish Championship, which is
exactly where the soft prices live. For those leagues we regress goals on shots
and shots on target *within that league* and use the fitted values as a proxy.

The regression is deliberately tiny — two coefficients — because the point is
to strip finishing luck out of a team's record, not to rebuild Opta.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np

# Sensible priors, used when a league has too few games to fit its own.
DEFAULT_SOT = 0.27          # goals per shot on target
DEFAULT_OFF_TARGET = 0.021  # goals per shot that missed


@dataclass
class XgProxy:
    """goals ≈ sot_coef · shots_on_target + off_coef · (shots − shots_on_target)."""

    sot_coef: float = DEFAULT_SOT
    off_coef: float = DEFAULT_OFF_TARGET
    fitted_on: int = 0
    league_code: str = ""

    def estimate(self, shots: float | None, sot: float | None) -> float | None:
        if sot is None:
            return None
        shots = shots if shots is not None else sot
        off_target = max(0.0, float(shots) - float(sot))
        return self.sot_coef * float(sot) + self.off_coef * off_target

    def describe(self) -> str:
        return (f"{self.sot_coef:.3f}·SoT + {self.off_coef:.3f}·off-target "
                f"(fitted on {self.fitted_on} team-matches)")


def fit_proxy(conn: sqlite3.Connection, league_code: str,
              min_rows: int = 80) -> XgProxy:
    """Least-squares fit of goals on (shots on target, shots off target)."""
    rows = conn.execute(
        'SELECT fthg, hs, hst, ftag, "as", ast FROM matches '
        "WHERE league_code = ? AND status = 'played' AND hst IS NOT NULL "
        "AND ast IS NOT NULL AND hs IS NOT NULL",
        (league_code,),
    ).fetchall()
    design, target = [], []
    for r in rows:
        for goals, shots, sot in ((r["fthg"], r["hs"], r["hst"]),
                                  (r["ftag"], r["as"], r["ast"])):
            if goals is None or shots is None or sot is None:
                continue
            if sot > shots:          # occasional feed error
                shots = sot
            design.append([sot, shots - sot])
            target.append(goals)
    if len(target) < min_rows:
        return XgProxy(league_code=league_code, fitted_on=len(target))

    matrix = np.asarray(design, dtype=float)
    values = np.asarray(target, dtype=float)
    coef, *_ = np.linalg.lstsq(matrix, values, rcond=None)
    sot_coef = float(np.clip(coef[0], 0.10, 0.45))
    off_coef = float(np.clip(coef[1], 0.0, 0.10))
    return XgProxy(sot_coef, off_coef, len(target), league_code)


def match_xg(row, proxy: XgProxy) -> tuple[float | None, float | None]:
    """Best available xG for one match: the real figure, else the proxy."""
    home = row["home_xg"] if "home_xg" in row.keys() else None
    away = row["away_xg"] if "away_xg" in row.keys() else None
    if home is not None and away is not None:
        return float(home), float(away)
    est_home = proxy.estimate(row["hs"] if "hs" in row.keys() else None,
                              row["hst"] if "hst" in row.keys() else None)
    est_away = proxy.estimate(row["as"] if "as" in row.keys() else None,
                              row["ast"] if "ast" in row.keys() else None)
    return est_home, est_away
