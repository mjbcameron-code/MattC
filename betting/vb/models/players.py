"""Player markets: shots on target, cards, anytime scorer.

These need per-player minutes and per-player events, which no free feed covers
for the lower divisions — so they run off the `player_stats` table, filled
either from an FBref/Sofascore export or by hand (`vb template players`).
Where a league has no player data loaded, the player markets are simply
skipped rather than guessed at.

Every rate is a per-90 rate scaled by two things: how long the player is
expected to be on the pitch, and how busy his team is expected to be in this
particular fixture relative to its own average.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass

MIN_MINUTES = 270          # below three full games, rates are too noisy to use


@dataclass
class PlayerProfile:
    player: str
    team_id: int
    position: str | None
    minutes: int
    apps: int
    goals: int
    shots: int
    sot: int
    fouls: int
    yellows: int
    reds: int

    @property
    def per90(self) -> float:
        return self.minutes / 90.0 if self.minutes else 0.0

    def rate(self, field: str) -> float:
        games = self.per90
        return getattr(self, field) / games if games else 0.0

    @property
    def expected_minutes(self) -> float:
        """How long he is likely to play, from how he has been used so far."""
        if not self.apps:
            return 0.0
        average = self.minutes / self.apps
        # Regulars finish games; squad players are pulled toward their average.
        return min(90.0, average * 1.02)

    @property
    def is_regular(self) -> bool:
        return self.minutes >= MIN_MINUTES and self.expected_minutes >= 45


def load_profiles(conn: sqlite3.Connection, team_id: int,
                  season: str | None = None) -> list[PlayerProfile]:
    sql = ("SELECT player, team_id, position, minutes, apps, goals, shots, sot, "
           "fouls, yellows, reds FROM player_stats WHERE team_id = ?")
    params: list = [team_id]
    if season:
        sql += " AND season = ?"
        params.append(season)
    return [PlayerProfile(**dict(row)) for row in conn.execute(sql, params)]


def _poisson_at_least(lam: float, n: int) -> float:
    """P(X >= n) for a Poisson rate."""
    if n <= 0:
        return 1.0
    total, term = 0.0, math.exp(-lam)
    for k in range(n):
        if k:
            term *= lam / k
        total += term
    return max(0.0, 1.0 - total)


@dataclass
class PlayerMarkets:
    """Prices for one player in one fixture."""

    profile: PlayerProfile
    minutes: float
    team_attack_index: float = 1.0     # this fixture's xG vs the team's average
    team_card_index: float = 1.0       # this fixture's card expectation vs average
    referee_index: float = 1.0         # referee's strictness vs league average

    @property
    def share(self) -> float:
        return self.minutes / 90.0

    def shots_on_target(self, line: float) -> float:
        lam = self.profile.rate("sot") * self.share * self.team_attack_index
        return _poisson_at_least(lam, math.ceil(line))

    def shots(self, line: float) -> float:
        lam = self.profile.rate("shots") * self.share * self.team_attack_index
        return _poisson_at_least(lam, math.ceil(line))

    def to_be_booked(self) -> float:
        lam = (self.profile.rate("yellows") + self.profile.rate("reds")) \
            * self.share * self.team_card_index * self.referee_index
        return 1.0 - math.exp(-max(0.0, lam))

    def anytime_scorer(self) -> float:
        lam = self.profile.rate("goals") * self.share * self.team_attack_index
        return 1.0 - math.exp(-max(0.0, lam))

    def probability(self, market: str, selection: str,
                    line: float | None) -> float | None:
        market = market.lower()
        if market in ("player_sot", "player_shots_on_target"):
            return self.shots_on_target(line if line is not None else 0.5)
        if market in ("player_shots",):
            return self.shots(line if line is not None else 0.5)
        if market in ("player_card", "player_to_be_booked"):
            p = self.to_be_booked()
            return p if selection in ("yes", "over", "card") else 1 - p
        if market in ("player_goal", "anytime_scorer"):
            p = self.anytime_scorer()
            return p if selection in ("yes", "over", "score") else 1 - p
        return None

    def describe(self) -> str:
        p = self.profile
        return (f"{p.player}: {p.rate('sot'):.2f} SoT/90, "
                f"{p.rate('yellows'):.2f} yellows/90, "
                f"~{self.minutes:.0f} mins expected")


def referee_index(conn: sqlite3.Connection, referee: str | None,
                  league_code: str, prior_games: float = 12.0) -> float:
    """How card-happy a referee is versus his league, shrunk toward 1.0."""
    if not referee:
        return 1.0
    row = conn.execute(
        "SELECT COUNT(*) AS games, AVG(COALESCE(hy,0) + COALESCE(ay,0)) AS cards "
        "FROM matches WHERE referee = ? AND league_code = ? AND status = 'played' "
        "AND hy IS NOT NULL",
        (referee, league_code),
    ).fetchone()
    league = conn.execute(
        "SELECT AVG(COALESCE(hy,0) + COALESCE(ay,0)) AS cards FROM matches "
        "WHERE league_code = ? AND status = 'played' AND hy IS NOT NULL",
        (league_code,),
    ).fetchone()
    if not row or not row["games"] or not league or not league["cards"]:
        return 1.0
    games, cards, league_cards = row["games"], row["cards"] or 0.0, league["cards"]
    # Shrink: a referee with four games seen barely moves the number.
    weight = games / (games + prior_games)
    return 1.0 + weight * ((cards / league_cards) - 1.0)


def build_markets(
    conn: sqlite3.Connection,
    team_id: int,
    team_attack_index: float = 1.0,
    team_card_index: float = 1.0,
    referee: str | None = None,
    league_code: str | None = None,
    season: str | None = None,
) -> list[PlayerMarkets]:
    """Every regular in a squad, priced up for one fixture."""
    ref_index = referee_index(conn, referee, league_code or "") if referee else 1.0
    out = []
    for profile in load_profiles(conn, team_id, season):
        if not profile.is_regular:
            continue
        out.append(PlayerMarkets(
            profile=profile,
            minutes=profile.expected_minutes,
            team_attack_index=team_attack_index,
            team_card_index=team_card_index,
            referee_index=ref_index,
        ))
    return out
