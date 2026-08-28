"""Everything the engine knows about one upcoming fixture, in one object.

`FixtureModel` pulls the league ratings, the corner and card rates, the player
profiles and the narrative signals together, applies team news, and exposes a
single `probability(market, selection, line, subject)` call that the value
engine can ask about any market on the coupon.

Champions League and Europa League ties are the awkward case: the two clubs
are rated in different leagues, on scales that have never met. Those ties are
bridged with the `league_strength` priors in settings.yaml and played on a
neutral-ish footing (the home edge in Europe is real but smaller).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..config import league as get_league, load_settings
from ..features.form import Signal, build_signals, news_impact, team_news
from ..repo import team_name
from .counts import CountProbs, RateModel, fit_rates
from .match import MatchProbs
from .players import PlayerMarkets, build_markets
from .ratings import LeagueModel, fit_league
from .simulate import SimulatedMatch, simulate_match
from .xg import XgProxy, fit_proxy


class ModelBank:
    """Fits each league once and hands the results out; fitting is the slow part."""

    def __init__(self, conn: sqlite3.Connection, as_of: datetime | None = None):
        self.conn = conn
        self.as_of = as_of or datetime.now()
        self._ratings: dict[str, LeagueModel | None] = {}
        self._corners: dict[str, RateModel | None] = {}
        self._cards: dict[str, RateModel | None] = {}
        self._proxies: dict[str, XgProxy] = {}
        self.settings = load_settings()

    def ratings(self, league_code: str) -> LeagueModel | None:
        if league_code not in self._ratings:
            self._ratings[league_code] = fit_league(self.conn, league_code, as_of=self.as_of)
        return self._ratings[league_code]

    def corners(self, league_code: str) -> RateModel | None:
        if league_code not in self._corners:
            self._corners[league_code] = fit_rates(self.conn, league_code, "corners",
                                                   as_of=self.as_of)
        return self._corners[league_code]

    def cards(self, league_code: str) -> RateModel | None:
        if league_code not in self._cards:
            self._cards[league_code] = fit_rates(self.conn, league_code, "cards",
                                                 as_of=self.as_of)
        return self._cards[league_code]

    def proxy(self, league_code: str) -> XgProxy:
        if league_code not in self._proxies:
            self._proxies[league_code] = fit_proxy(self.conn, league_code)
        return self._proxies[league_code]

    def home_league(self, team_id: int, fallback: str) -> str:
        row = self.conn.execute("SELECT league_code FROM teams WHERE id = ?",
                                (team_id,)).fetchone()
        code = row["league_code"] if row else None
        return code if code and code in self.settings.get("league_strength", {}) else fallback

    def league_strength(self, league_code: str) -> float:
        return float((self.settings.get("league_strength", {}) or {}).get(league_code, 0.0))


@dataclass
class FixtureModel:
    match_id: int
    league_code: str
    kickoff: str
    home_id: int
    away_id: int
    home: str
    away: str
    probs: MatchProbs
    corners: CountProbs | None = None
    cards: CountProbs | None = None
    red_rate: float = 0.08
    players: dict[str, PlayerMarkets] = field(default_factory=dict)
    signals: list[Signal] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    neutral: bool = False
    # Matches the ratings model has seen for the *less* observed of the two
    # clubs — the binding constraint on how much this fixture can be trusted.
    matches_seen: int = 0

    @property
    def label(self) -> str:
        return f"{self.home} v {self.away}"

    def probability(self, market: str, selection: str, line: float | None = None,
                    subject: str | None = None) -> float | None:
        """One entry point for every market this fixture supports."""
        market = market.lower()
        if subject:
            player = self.players.get(subject)
            if player is None:
                return None
            return player.probability(market, selection, line)
        if market == "corners":
            return self.corners.probability(market, selection, line) if self.corners else None
        if market == "cards":
            return self.cards.probability(market, selection, line) if self.cards else None
        if market == "booking_points" and self.cards and line is not None:
            over = self.cards.booking_points_over(line, self.red_rate)
            return over if selection.lower() == "over" else 1 - over
        return self.probs.probability(market, selection, line)

    def simulate(self, n: int = 40_000, seed: int | None = None) -> SimulatedMatch:
        players = {
            name: {
                "side": "home" if market.profile.team_id == self.home_id else "away",
                "sot": market.profile.rate("sot") * market.share * market.team_attack_index,
                "shots": market.profile.rate("shots") * market.share * market.team_attack_index,
                "cards": (market.profile.rate("yellows") + market.profile.rate("reds"))
                         * market.share * market.team_card_index * market.referee_index,
                "goals": market.profile.rate("goals") * market.share * market.team_attack_index,
            }
            for name, market in self.players.items()
        }
        return simulate_match(
            self.probs.lam_home, self.probs.lam_away,
            corner_home=self.corners.home_mean if self.corners else None,
            corner_away=self.corners.away_mean if self.corners else None,
            card_home=self.cards.home_mean if self.cards else None,
            card_away=self.cards.away_mean if self.cards else None,
            red_rate=self.red_rate, players=players, n=n, seed=seed,
        )

    def summary(self) -> dict[str, Any]:
        out = {"fixture": self.label, "kickoff": self.kickoff, **self.probs.summary()}
        if self.corners:
            out["corners"] = round(float(self.corners.total), 1)
        if self.cards:
            out["cards"] = round(float(self.cards.total), 1)
        return out


def build_fixture(
    conn: sqlite3.Connection,
    match: sqlite3.Row,
    bank: ModelBank,
    with_players: bool = True,
    with_signals: bool = True,
) -> FixtureModel | None:
    """Assemble the full model for one scheduled match."""
    settings = bank.settings
    league_code = match["league_code"]
    home_id, away_id = match["home_id"], match["away_id"]
    league = get_league(league_code)

    if league.is_uefa:
        result = _uefa_rates(conn, bank, home_id, away_id, league_code)
        if result is None:
            return None
        lam_home, lam_away, rho, rating_league = result
        neutral = False
    else:
        model = bank.ratings(league_code)
        if model is None:
            return None
        lam_home, lam_away = model.expected_goals(home_id, away_id)
        rho, rating_league, neutral = model.rho, league_code, False

    # --- team news moves the expectation ------------------------------------
    kickoff = datetime.fromisoformat(match["kickoff"][:19])
    attack_factor = float(settings.get("model.news_attack_factor", 0.55))
    defence_factor = float(settings.get("model.news_defence_factor", 0.40))
    notes: list[str] = []
    for side, team_id in (("home", home_id), ("away", away_id)):
        impact = news_impact(team_news(conn, team_id, kickoff))
        if abs(impact) < 0.02:
            continue
        if side == "home":
            lam_home *= max(0.5, 1 - impact * attack_factor)
            lam_away *= min(1.6, 1 + impact * defence_factor)
        else:
            lam_away *= max(0.5, 1 - impact * attack_factor)
            lam_home *= min(1.6, 1 + impact * defence_factor)
        notes.append(f"{team_name(conn, team_id)} team news impact {impact:+.0%}")

    probs = MatchProbs(lam_home, lam_away, rho)

    # --- corners and cards ---------------------------------------------------
    corners = cards = None
    red_rate = 0.08
    corner_model = bank.corners(rating_league)
    if corner_model is not None:
        ch, ca = corner_model.expected(home_id, away_id, neutral=neutral)
        corners = CountProbs(ch, ca, corner_model.dispersion)
    card_model = bank.cards(rating_league)
    if card_model is not None:
        kh, ka = card_model.expected(home_id, away_id, neutral=neutral)
        cards = CountProbs(kh, ka, card_model.dispersion)
        red_rate = card_model.red_rate

    fixture = FixtureModel(
        match_id=match["id"], league_code=league_code, kickoff=match["kickoff"],
        home_id=home_id, away_id=away_id,
        home=team_name(conn, home_id), away=team_name(conn, away_id),
        probs=probs, corners=corners, cards=cards, red_rate=red_rate,
        notes=notes, neutral=neutral,
        matches_seen=_matches_seen(bank, rating_league, home_id, away_id),
    )

    # --- players --------------------------------------------------------------
    if with_players:
        ratings_model = bank.ratings(rating_league)
        league_goals = 1.4
        if ratings_model is not None:
            import math

            league_goals = math.exp(ratings_model.base)
        card_league = (card_model.league_home + card_model.league_away) / 2 if card_model else 2.0
        for side, team_id in (("home", home_id), ("away", away_id)):
            team_lambda = lam_home if side == "home" else lam_away
            team_cards = (cards.home_mean if side == "home" else cards.away_mean) \
                if cards else card_league
            attack_index = team_lambda / league_goals if league_goals else 1.0
            card_index = team_cards / card_league if card_league else 1.0
            for market in build_markets(
                conn, team_id,
                team_attack_index=max(0.5, min(1.8, attack_index)),
                team_card_index=max(0.5, min(1.8, card_index)),
                referee=match["referee"] if "referee" in match.keys() else None,
                league_code=league_code,
            ):
                fixture.players[market.profile.player] = market

    if with_signals:
        fixture.signals = build_signals(conn, match, league_code, bank.proxy(rating_league))
    return fixture


def _uefa_rates(conn: sqlite3.Connection, bank: ModelBank, home_id: int,
                away_id: int, league_code: str):
    """Rate a European tie by borrowing each club's domestic strength.

    The two ratings live on different scales, so each is shifted by its
    league's strength prior before they are compared.
    """
    import math

    home_league = bank.home_league(home_id, "E0")
    away_league = bank.home_league(away_id, "E0")
    home_model = bank.ratings(home_league)
    away_model = bank.ratings(away_league)
    if home_model is None or away_model is None:
        return None

    home_shift = bank.league_strength(home_league)
    away_shift = bank.league_strength(away_league)
    base = (home_model.base + away_model.base) / 2
    # Home advantage in Europe is real but smaller than in a domestic league.
    home_adv = 0.7 * (home_model.home_adv + away_model.home_adv) / 2

    lam_home = math.exp(
        base + (home_model.attack.get(home_id, 0.0) + home_shift)
        - (away_model.defence.get(away_id, 0.0) + away_shift) + home_adv
    )
    lam_away = math.exp(
        base + (away_model.attack.get(away_id, 0.0) + away_shift)
        - (home_model.defence.get(home_id, 0.0) + home_shift)
    )
    rho = (home_model.rho + away_model.rho) / 2
    return max(0.2, lam_home), max(0.2, lam_away), rho, home_league


def _matches_seen(bank: ModelBank, league_code: str, home_id: int, away_id: int) -> int:
    model = bank.ratings(league_code)
    if model is None:
        return 0
    return min(model.matches_per_team.get(home_id, 0),
               model.matches_per_team.get(away_id, 0))
