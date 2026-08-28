"""Team strength: a time-weighted Dixon-Coles fit, run per league.

The model is the standard one — each club gets an attack and a defence
parameter, the league gets a home advantage and a low-score correlation term
rho — with three practical additions:

1. **Time decay.** A result from last August tells you less than one from last
   week, so each match is weighted exp(−ξ·days_ago) with ξ set by the
   half_life_days setting.
2. **xG as well as goals.** The same model is fitted twice, once on goals and
   once on expected goals (real where a feed exists, the shot-based proxy where
   it doesn't), and the two sets of strengths are blended. Goals carry
   finishing ability; xG carries everything else and carries it sooner.
3. **Ridge shrinkage.** A promoted side with six games played is pulled toward
   the league average rather than being taken at face value.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from scipy.optimize import minimize

from ..config import load_settings
from .xg import XgProxy, fit_proxy, match_xg


@dataclass
class LeagueModel:
    """Fitted strengths for one league, plus everything needed to use them."""

    league_code: str
    as_of: str
    attack: dict[int, float]
    defence: dict[int, float]
    home_adv: float
    rho: float
    base: float                       # log mean goals per team per game
    matches_per_team: dict[int, int]
    xg_proxy: XgProxy | None = None
    n_matches: int = 0

    def expected_goals(self, home_id: int, away_id: int,
                       neutral: bool = False) -> tuple[float, float]:
        home_edge = 0.0 if neutral else self.home_adv
        lam_home = math.exp(
            self.base + self.attack.get(home_id, 0.0)
            - self.defence.get(away_id, 0.0) + home_edge
        )
        lam_away = math.exp(
            self.base + self.attack.get(away_id, 0.0)
            - self.defence.get(home_id, 0.0)
        )
        return max(0.15, lam_home), max(0.15, lam_away)

    def strength(self, team_id: int) -> float:
        """One number for a club, higher is better.

        Defence enters the rate as `−defence`, so a big positive defence term
        means a side that concedes little: net strength adds the two.
        """
        return self.attack.get(team_id, 0.0) + self.defence.get(team_id, 0.0)

    def table(self) -> list[tuple[int, float, float, float]]:
        teams = set(self.attack) | set(self.defence)
        return sorted(
            ((t, self.attack.get(t, 0.0), self.defence.get(t, 0.0), self.strength(t))
             for t in teams),
            key=lambda row: -row[3],
        )


def _decay_weights(dates: list[str], as_of: datetime, half_life: float) -> np.ndarray:
    xi = math.log(2) / max(1.0, half_life)
    out = np.empty(len(dates))
    for i, date in enumerate(dates):
        try:
            days = (as_of - datetime.fromisoformat(date[:19])).days
        except ValueError:
            days = 0
        out[i] = math.exp(-xi * max(0, days))
    return out


def _dc_tau(lam: np.ndarray, mu: np.ndarray, x: np.ndarray, y: np.ndarray,
            rho: float) -> np.ndarray:
    """Dixon-Coles correction for the 0-0/1-0/0-1/1-1 cluster."""
    tau = np.ones_like(lam)
    both_zero = (x == 0) & (y == 0)
    home_one = (x == 1) & (y == 0)
    away_one = (x == 0) & (y == 1)
    one_one = (x == 1) & (y == 1)
    tau[both_zero] = 1.0 - lam[both_zero] * mu[both_zero] * rho
    tau[away_one] = 1.0 + lam[away_one] * rho
    tau[home_one] = 1.0 + mu[home_one] * rho
    tau[one_one] = 1.0 - rho
    return np.clip(tau, 1e-6, None)


def _fit_core(
    home_idx: np.ndarray, away_idx: np.ndarray,
    home_goals: np.ndarray, away_goals: np.ndarray,
    weights: np.ndarray, n_teams: int, base: float,
    ridge: float, use_tau: bool,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Weighted maximum likelihood. Returns (attack, defence, home_adv, rho)."""

    def unpack(params: np.ndarray):
        attack = params[:n_teams]
        defence = params[n_teams:2 * n_teams]
        home_adv = params[2 * n_teams]
        rho = params[2 * n_teams + 1] if use_tau else 0.0
        return attack, defence, home_adv, rho

    def negative_log_likelihood(params: np.ndarray) -> float:
        attack, defence, home_adv, rho = unpack(params)
        log_lam = base + attack[home_idx] - defence[away_idx] + home_adv
        log_mu = base + attack[away_idx] - defence[home_idx]
        log_lam = np.clip(log_lam, -4.0, 2.5)
        log_mu = np.clip(log_mu, -4.0, 2.5)
        lam, mu = np.exp(log_lam), np.exp(log_mu)
        # Poisson log-density without the constant term (valid for continuous
        # observations too, which is what lets us fit the same model on xG).
        ll = (-lam + home_goals * log_lam) + (-mu + away_goals * log_mu)
        if use_tau:
            ll = ll + np.log(_dc_tau(lam, mu, home_goals, away_goals, rho))
        penalty = ridge * float(np.sum(attack ** 2) + np.sum(defence ** 2))
        return -float(np.sum(weights * ll)) + penalty

    start = np.zeros(2 * n_teams + 2)
    start[2 * n_teams] = 0.25       # a plausible opening home advantage
    bounds = [(-2.0, 2.0)] * (2 * n_teams) + [(-0.5, 0.9), (-0.25, 0.25)]
    if not use_tau:
        bounds[-1] = (0.0, 0.0)

    result = minimize(
        negative_log_likelihood, start, method="L-BFGS-B", bounds=bounds,
        options={"maxiter": 600, "ftol": 1e-9},
    )
    attack, defence, home_adv, rho = unpack(result.x)
    # Centre the attack/defence scale — it is only identified up to a shift.
    attack = attack - attack.mean()
    defence = defence - defence.mean()
    return attack, defence, float(home_adv), float(rho)


def fit_league(
    conn: sqlite3.Connection,
    league_code: str,
    as_of: datetime | None = None,
    half_life: float | None = None,
    seasons: int | None = None,
    xg_weight: float | None = None,
) -> LeagueModel | None:
    """Fit the model for one league on everything played before ``as_of``."""
    settings = load_settings()
    as_of = as_of or datetime.now()
    half_life = half_life or float(settings.get("model.half_life_days", 180))
    xg_weight = settings.get("model.xg_weight", 0.65) if xg_weight is None else xg_weight
    min_matches = int(settings.get("model.min_matches_per_team", 6))
    shrink_at = float(settings.get("model.shrinkage_matches", 10))

    rows = conn.execute(
        'SELECT kickoff, home_id, away_id, fthg, ftag, hs, "as", hst, ast, '
        "home_xg, away_xg FROM matches WHERE league_code = ? AND status = 'played' "
        "AND fthg IS NOT NULL AND kickoff < ? ORDER BY kickoff",
        (league_code, as_of.isoformat()),
    ).fetchall()
    if len(rows) < 20:
        return None

    proxy = fit_proxy(conn, league_code)
    teams = sorted({r["home_id"] for r in rows} | {r["away_id"] for r in rows})
    index = {team: i for i, team in enumerate(teams)}
    n = len(teams)

    home_idx = np.array([index[r["home_id"]] for r in rows])
    away_idx = np.array([index[r["away_id"]] for r in rows])
    hg = np.array([r["fthg"] for r in rows], dtype=float)
    ag = np.array([r["ftag"] for r in rows], dtype=float)
    weights = _decay_weights([r["kickoff"] for r in rows], as_of, half_life)

    counts: dict[int, int] = {t: 0 for t in teams}
    for r in rows:
        counts[r["home_id"]] += 1
        counts[r["away_id"]] += 1

    base = math.log(max(0.4, float(np.average(np.concatenate([hg, ag]),
                                              weights=np.concatenate([weights, weights])))))
    # Ridge strength: with `shrink_at` effective matches a team is pulled
    # roughly halfway to the league mean.
    effective = float(weights.sum())
    ridge = max(1e-4, effective / max(1.0, shrink_at * n))

    attack_g, defence_g, home_g, rho = _fit_core(
        home_idx, away_idx, hg, ag, weights, n, base, ridge, use_tau=True
    )

    # Second pass on expected goals.
    hx, ax, keep = [], [], []
    for i, r in enumerate(rows):
        home_xg, away_xg = match_xg(r, proxy)
        if home_xg is None or away_xg is None:
            continue
        hx.append(home_xg)
        ax.append(away_xg)
        keep.append(i)

    if len(keep) >= max(20, 0.4 * len(rows)) and xg_weight > 0:
        keep_arr = np.array(keep)
        xg_base = math.log(max(0.4, float(np.average(
            np.concatenate([hx, ax]),
            weights=np.concatenate([weights[keep_arr], weights[keep_arr]]),
        ))))
        attack_x, defence_x, home_x, _ = _fit_core(
            home_idx[keep_arr], away_idx[keep_arr],
            np.array(hx), np.array(ax), weights[keep_arr], n, xg_base,
            ridge, use_tau=False,
        )
        w = float(xg_weight)
        attack = (1 - w) * attack_g + w * attack_x
        defence = (1 - w) * defence_g + w * defence_x
        home_adv = (1 - w) * home_g + w * home_x
    else:
        attack, defence, home_adv = attack_g, defence_g, home_g

    # Teams with barely any football played get pulled further to the mean.
    for team, i in index.items():
        played = counts[team]
        if played < min_matches:
            factor = played / max(1.0, min_matches)
            attack[i] *= factor
            defence[i] *= factor

    return LeagueModel(
        league_code=league_code,
        as_of=as_of.isoformat(timespec="seconds"),
        attack={t: float(attack[i]) for t, i in index.items()},
        defence={t: float(defence[i]) for t, i in index.items()},
        home_adv=float(home_adv),
        rho=float(rho),
        base=base,
        matches_per_team=counts,
        xg_proxy=proxy,
        n_matches=len(rows),
    )


def save(conn: sqlite3.Connection, model: LeagueModel) -> None:
    for team_id in set(model.attack) | set(model.defence):
        conn.execute(
            "INSERT INTO ratings (league_code, team_id, as_of, attack, defence, matches) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(league_code, team_id, as_of) DO UPDATE SET "
            "attack=excluded.attack, defence=excluded.defence, matches=excluded.matches",
            (model.league_code, team_id, model.as_of[:10],
             model.attack.get(team_id, 0.0), model.defence.get(team_id, 0.0),
             model.matches_per_team.get(team_id, 0)),
        )
    conn.execute(
        "INSERT INTO league_params (league_code, as_of, home_adv, rho, base_goals) "
        "VALUES (?,?,?,?,?) ON CONFLICT(league_code, as_of) DO UPDATE SET "
        "home_adv=excluded.home_adv, rho=excluded.rho, base_goals=excluded.base_goals",
        (model.league_code, model.as_of[:10], model.home_adv, model.rho,
         math.exp(model.base)),
    )


def fit_all(conn: sqlite3.Connection, league_codes: list[str],
            as_of: datetime | None = None) -> dict[str, LeagueModel]:
    out: dict[str, LeagueModel] = {}
    for code in league_codes:
        model = fit_league(conn, code, as_of=as_of)
        if model is not None:
            out[code] = model
            save(conn, model)
    return out
