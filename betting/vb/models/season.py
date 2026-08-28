"""Season simulation, for the long-term markets.

Title, top four, promotion, relegation, top scorer — these are the bets you
place once and carry for months, and they are also the ones where a model has
the biggest advantage over a casual punter, because working out how often a
side finishes in the top two requires playing the rest of the season out a few
thousand times rather than eyeballing the table.

Every remaining fixture is simulated from the same ratings the match model
uses, added to the points already banked, and the finishing positions counted.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from ..repo import team_name
from .ratings import LeagueModel


@dataclass
class SeasonOutlook:
    """Finishing-position probabilities for every club in a league."""

    league_code: str
    season: str
    simulations: int
    teams: dict[int, str]
    current_points: dict[int, int]
    played: dict[int, int]
    position_counts: dict[int, np.ndarray]       # team_id -> counts by position
    expected_points: dict[int, float]

    def probability_position(self, team_id: int, top: int) -> float:
        """P(finishing in the top `top` places)."""
        counts = self.position_counts.get(team_id)
        if counts is None:
            return 0.0
        return float(counts[:top].sum() / self.simulations)

    def probability_bottom(self, team_id: int, bottom: int) -> float:
        counts = self.position_counts.get(team_id)
        if counts is None:
            return 0.0
        return float(counts[-bottom:].sum() / self.simulations)

    def probability_between(self, team_id: int, first: int, last: int) -> float:
        """P(finishing between positions `first` and `last`, both inclusive, 1-indexed)."""
        counts = self.position_counts.get(team_id)
        if counts is None:
            return 0.0
        return float(counts[first - 1:last].sum() / self.simulations)

    def title(self, team_id: int) -> float:
        return self.probability_position(team_id, 1)

    def table(self) -> list[tuple[str, float, float, float]]:
        rows = []
        for team_id, name in self.teams.items():
            rows.append((
                name,
                self.expected_points.get(team_id, 0.0),
                self.title(team_id),
                self.probability_bottom(team_id, 3),
            ))
        return sorted(rows, key=lambda r: -r[1])

    def probability(self, market: str, team_id: int, places: int | None = None) -> float | None:
        market = market.lower()
        if market in ("winner", "title", "outright"):
            return self.title(team_id)
        if market in ("top_two", "automatic_promotion"):
            return self.probability_position(team_id, places or 2)
        if market in ("top_four", "top_4"):
            return self.probability_position(team_id, places or 4)
        if market in ("top_six", "playoffs", "top_6"):
            return self.probability_position(team_id, places or 6)
        if market in ("relegation", "bottom_three"):
            return self.probability_bottom(team_id, places or 3)
        if market == "top_half":
            half = max(1, len(self.teams) // 2)
            return self.probability_position(team_id, half)
        return None


def simulate_season(
    conn: sqlite3.Connection,
    model: LeagueModel,
    season: str,
    simulations: int = 5000,
    as_of: datetime | None = None,
    seed: int | None = None,
    complete_schedule: bool = True,
) -> SeasonOutlook | None:
    """Play out every remaining fixture `simulations` times.

    Result feeds publish what has happened, not what is still to come, and the
    fixtures feed only reaches a week ahead — so by default the rest of the
    schedule is *derived*: in a double round robin every pair of clubs meets
    home and away, so whatever has not been played yet is still to come.
    """
    as_of = as_of or datetime.now()
    rng = np.random.default_rng(seed)
    league_code = model.league_code

    played = conn.execute(
        "SELECT home_id, away_id, fthg, ftag FROM matches WHERE league_code = ? "
        "AND season = ? AND status = 'played' AND fthg IS NOT NULL",
        (league_code, season),
    ).fetchall()
    remaining = conn.execute(
        "SELECT home_id, away_id FROM matches WHERE league_code = ? AND season = ? "
        "AND status = 'scheduled'",
        (league_code, season),
    ).fetchall()
    if not played:
        return None
    if complete_schedule:
        remaining = _infer_remaining(played, remaining)

    points: dict[int, int] = defaultdict(int)
    goal_diff: dict[int, int] = defaultdict(int)
    games: dict[int, int] = defaultdict(int)
    for r in played:
        home, away, hg, ag = r["home_id"], r["away_id"], r["fthg"], r["ftag"]
        games[home] += 1
        games[away] += 1
        goal_diff[home] += hg - ag
        goal_diff[away] += ag - hg
        if hg > ag:
            points[home] += 3
        elif hg == ag:
            points[home] += 1
            points[away] += 1
        else:
            points[away] += 3

    teams = sorted(set(games) | {r["home_id"] for r in remaining}
                   | {r["away_id"] for r in remaining})
    index = {team: i for i, team in enumerate(teams)}
    n_teams = len(teams)

    base_points = np.array([points.get(t, 0) for t in teams], dtype=float)
    base_gd = np.array([goal_diff.get(t, 0) for t in teams], dtype=float)
    sim_points = np.tile(base_points, (simulations, 1))
    sim_gd = np.tile(base_gd, (simulations, 1))

    for fixture in remaining:
        home, away = fixture["home_id"], fixture["away_id"]
        if home not in index or away not in index:
            continue
        lam_home, lam_away = model.expected_goals(home, away)
        hg = rng.poisson(lam_home, simulations)
        ag = rng.poisson(lam_away, simulations)
        h, a = index[home], index[away]
        sim_points[:, h] += np.where(hg > ag, 3, np.where(hg == ag, 1, 0))
        sim_points[:, a] += np.where(ag > hg, 3, np.where(hg == ag, 1, 0))
        sim_gd[:, h] += hg - ag
        sim_gd[:, a] += ag - hg

    # Rank by points then goal difference; a tiny random term breaks exact ties.
    score = sim_points * 1000 + sim_gd + rng.random(sim_points.shape) * 0.01
    order = np.argsort(-score, axis=1)
    positions = np.empty_like(order)
    rows = np.arange(simulations)[:, None]
    positions[rows, order] = np.arange(n_teams)[None, :]

    position_counts: dict[int, np.ndarray] = {}
    for team, i in index.items():
        position_counts[team] = np.bincount(positions[:, i], minlength=n_teams)

    return SeasonOutlook(
        league_code=league_code, season=season, simulations=simulations,
        teams={t: team_name(conn, t) for t in teams},
        current_points={t: int(points.get(t, 0)) for t in teams},
        played={t: int(games.get(t, 0)) for t in teams},
        position_counts=position_counts,
        expected_points={t: float(sim_points[:, index[t]].mean()) for t in teams},
    )


def _infer_remaining(played, scheduled) -> list[dict]:
    """Work out the rest of the schedule from who has not yet met whom.

    A league season is a double round robin, so the fixtures still to come are
    exactly the ordered pairs that have not been played. Anything already in the
    database as a scheduled fixture is kept as-is and not duplicated.
    """
    teams = sorted({r["home_id"] for r in played} | {r["away_id"] for r in played})
    done = {(r["home_id"], r["away_id"]) for r in played}
    known = {(r["home_id"], r["away_id"]) for r in scheduled}
    out = [{"home_id": r["home_id"], "away_id": r["away_id"]} for r in scheduled]
    for home in teams:
        for away in teams:
            if home == away:
                continue
            pair = (home, away)
            if pair not in done and pair not in known:
                out.append({"home_id": home, "away_id": away})
    return out
