"""Deciding whether a price is worth taking, and how much to put on it.

Three ideas do the work here.

**Blend, don't override.** The market is the best single forecaster in
football. A model that disagrees with it by twenty points is usually wrong, not
brilliant. So the model's probability and the market's devigged probability are
blended in log-odds space, with the weight given to the model set per league:
low in the Premier League and in Europe where the prices are sharp, higher in
League Two and the National League where they are not.

**Edge, then evidence.** A bet needs both a positive expected value at the best
available price *and* supporting signals — form, xG, team news, rest. An edge
with no story behind it is usually a stale price or a mis-mapped team.

**Fractional Kelly.** Stakes are quarter-Kelly by default and capped, because
the model's probabilities are estimates, and full Kelly on an estimate is a
fast way to lose a bankroll.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ..config import league as get_league, load_settings
from ..features.form import Signal
from ..models.fixture import FixtureModel
from .odds import Quote, best_prices, consensus_fair, latest_quotes

# Markets we know how to model, in the order they read best in a write-up.
MODELLED_MARKETS = [
    "h2h", "totals", "btts", "ah", "double_chance", "dnb", "team_totals",
    "corners", "cards", "booking_points", "correct_score", "clean_sheet",
    "player_sot", "player_shots", "player_card", "player_goal",
]

MARKET_LABELS = {
    "h2h": "Match result",
    "totals": "Goals",
    "btts": "Both teams to score",
    "ah": "Asian handicap",
    "double_chance": "Double chance",
    "dnb": "Draw no bet",
    "team_totals": "Team goals",
    "corners": "Corners",
    "cards": "Cards",
    "booking_points": "Booking points",
    "correct_score": "Correct score",
    "clean_sheet": "Clean sheet",
    "player_sot": "Player shots on target",
    "player_shots": "Player shots",
    "player_card": "Player to be booked",
    "player_goal": "Anytime goalscorer",
}


def logit(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def inverse_logit(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def confidence_weight(base_weight: float, matches_seen: int, k: float = 8.0) -> float:
    """Shade the model's weight down when it has seen little football.

    Selection makes this matter more than it looks. We only bet where the model
    disagrees with the market in our favour, so the bets we place are exactly
    the ones where our estimation error happened to point the right way — the
    winner's curse. The noisier the estimate, the worse that bias, so a league
    where every club has played eight games gets less of a say than one where
    they have played thirty.
    """
    if matches_seen <= 0:
        return 0.0
    return base_weight * (matches_seen / (matches_seen + k))


def blend(model_prob: float, market_prob: float | None, weight: float) -> float:
    """Combine model and market on the log-odds scale.

    Averaging probabilities directly drags everything toward 50%; averaging
    log-odds keeps the blend sensible at both ends, where these markets live.
    """
    if market_prob is None or market_prob <= 0 or market_prob >= 1:
        return model_prob
    return inverse_logit(weight * logit(model_prob) + (1 - weight) * logit(market_prob))


def kelly_fraction(prob: float, price: float, push_prob: float = 0.0) -> float:
    """Full-Kelly stake as a fraction of bankroll, allowing for a push.

    A push returns the stake, so it neither wins nor loses: the bet is sized on
    the live market (win versus lose) and then scaled down by how often the
    stake simply comes back.
    """
    live = prob + max(0.0, 1 - prob - push_prob)
    if live <= 0:
        return 0.0
    p_eff = prob / live
    b = price - 1.0
    if b <= 0:
        return 0.0
    fraction = (p_eff * b - (1 - p_eff)) / b
    return max(0.0, fraction) * live


@dataclass
class Candidate:
    """One priced-up betting opportunity."""

    fixture: FixtureModel
    market: str
    selection: str
    line: float | None
    price: float
    bookmaker: str
    model_prob: float
    market_prob: float | None
    blended_prob: float
    edge: float
    kelly: float
    stake_pts: float
    push_prob: float = 0.0
    subject: str | None = None
    signals: list[Signal] = field(default_factory=list)
    books_seen: int = 0
    blend_weight: float = 0.0

    @property
    def league_code(self) -> str:
        return self.fixture.league_code

    @property
    def fair_price(self) -> float:
        return 1.0 / self.blended_prob if self.blended_prob > 0 else float("inf")

    @property
    def market_label(self) -> str:
        return MARKET_LABELS.get(self.market, self.market)

    def selection_text(self) -> str:
        """How the bet reads on a betting slip."""
        home, away = self.fixture.home, self.fixture.away
        sel, line = self.selection, self.line
        if self.subject:
            base = {
                "player_sot": f"{self.subject} {line:g}+ shots on target"
                              if line is not None else f"{self.subject} shot on target",
                "player_shots": f"{self.subject} {line:g}+ shots" if line is not None
                                else f"{self.subject} to have a shot",
                "player_card": f"{self.subject} to be booked",
                "player_goal": f"{self.subject} to score anytime",
            }.get(self.market, f"{self.subject} {self.market} {sel}")
            if self.market in ("player_sot", "player_shots") and line is not None:
                base = f"{self.subject} {math.ceil(line):g}+ " + (
                    "shots on target" if self.market == "player_sot" else "shots")
            return base
        if self.market == "h2h":
            return {"home": home, "draw": "Draw", "away": away}[sel]
        if self.market == "double_chance":
            return {"1x": f"{home} or draw", "12": f"{home} or {away}",
                    "x2": f"{away} or draw"}[sel.lower()]
        if self.market == "dnb":
            return f"{home if sel == 'home' else away} draw no bet"
        if self.market == "ah":
            # Stored from the home team's view; shown from the backed team's.
            side = home if sel == "home" else away
            shown = line if sel == "home" else -line
            return f"{side} {shown:+g} (Asian handicap)"
        if self.market == "totals":
            return f"{sel.capitalize()} {line:g} goals"
        if self.market == "team_totals":
            side, _, direction = sel.partition("_")
            team = home if side == "home" else away
            return f"{team} {direction} {line:g} goals"
        if self.market == "btts":
            return "Both teams to score" if sel == "yes" else "Both teams to score — no"
        if self.market == "corners":
            if sel in ("over", "under"):
                return f"{sel.capitalize()} {line:g} corners"
            side, _, direction = sel.partition("_")
            team = home if side == "home" else away
            return f"{team} {direction} {line:g} corners"
        if self.market == "cards":
            if sel in ("over", "under"):
                return f"{sel.capitalize()} {line:g} cards"
            side, _, direction = sel.partition("_")
            team = home if side == "home" else away
            return f"{team} {direction} {line:g} cards"
        if self.market == "booking_points":
            return f"{sel.capitalize()} {line:g} booking points"
        if self.market == "correct_score":
            return f"Correct score {sel}"
        if self.market == "clean_sheet":
            return f"{home if sel == 'home' else away} clean sheet"
        return f"{self.market} {sel}"

    def favours(self) -> str:
        """Which way this bet leans, for matching against the signals."""
        if self.market in ("h2h", "ah", "dnb", "clean_sheet"):
            return self.selection if self.selection in ("home", "away") else ""
        if self.market == "double_chance":
            return {"1x": "home", "x2": "away", "12": ""}.get(self.selection.lower(), "")
        if self.selection in ("over", "yes"):
            return "over"
        if self.selection in ("under", "no"):
            return "under"
        if self.selection.endswith("_over"):
            return "over"
        if self.selection.endswith("_under"):
            return "under"
        return ""

    # Which signal topics count as evidence for which markets. A corner trend
    # is no argument for both teams to score, and a card-happy pair of sides is
    # no argument for a home win.
    RELEVANT_TOPICS = {
        "result": {"result"},
        "goals": {"goals", "result"},
        "corners": {"corners"},
        "cards": {"cards"},
        "players": {"result", "cards"},
    }

    def supporting_signals(self) -> list[Signal]:
        from ..tips.select import MARKET_FAMILY

        family = MARKET_FAMILY.get(self.market, "result")
        topics = self.RELEVANT_TOPICS.get(family, {"result"})
        relevant = [s for s in self.fixture.signals if s.topic in topics]
        want = self.favours()
        if not want:
            return [s for s in relevant if s.strength >= 0.5]
        return [s for s in relevant if s.favours == want]

    def confidence(self) -> int:
        """One to five stars, from the edge, the evidence and the price."""
        score = 0.0
        score += min(2.5, self.edge / 0.04)                 # edge is worth up to 2.5
        support = self.supporting_signals()
        score += min(1.5, sum(s.strength for s in support) / 1.2)
        if self.books_seen >= 5:
            score += 0.5
        if self.price > 8.0:
            score -= 0.5
        if self.market_prob is None:
            score -= 0.5
        return int(max(1, min(5, round(score))))


class Trace:
    """A tally of why prices did not become bets, kept per league.

    The engine discards candidates silently, which makes the obvious question
    — "why is there nothing from the National League this week?" — impossible
    to answer. And the answer matters, because "no value there" and "no prices
    there" produce an identical card. One is discipline working; the other is a
    feed that has quietly stopped arriving.
    """

    #: Reasons in the order the engine applies them, so a report reads as a
    #: funnel from every quoted price down to the ones that became bets.
    ORDER = [
        "no model for this fixture",
        "market not modelled",
        "no price on file",
        "only unbettable prices (exchange or aggregate)",
        "model has no view",
        "model rates it below the floor",
        "price outside the odds limits",
        "edge below the minimum",
        "edge above the maximum (treated as a data fault)",
        "edge too thin in probability",
        "stake rounds below the minimum",
        # Everything above happens while pricing. Below is the second stage,
        # where a priced-up candidate still has to survive the discipline.
        "priced up",
        "not enough supporting signals",
        "same angle already taken",
        "two bets on that match already",
        "league is already at its cap",
        "tipped",
    ]

    def __init__(self) -> None:
        self.counts: dict[str, Counter] = defaultdict(Counter)

    def note(self, league_code: str, reason: str, n: int = 1) -> None:
        self.counts[league_code][reason] += n

    def leagues(self) -> list[str]:
        return sorted(self.counts)

    def total(self, league_code: str) -> int:
        """How many prices were looked at.

        Only the pricing stage counts. The reasons below "priced up" are a
        partition of it — every candidate that survives pricing is then either
        tipped or dropped by the discipline — so adding both stages would
        count those twice.
        """
        counts = self.counts[league_code]
        cut = self.ORDER.index("priced up") + 1
        return sum(counts[r] for r in self.ORDER[:cut]) + sum(
            n for r, n in counts.items() if r not in self.ORDER)

    def to_json(self) -> str:
        return json.dumps({c: dict(v) for c, v in self.counts.items()},
                          sort_keys=True)

    @classmethod
    def from_json(cls, blob: str | None) -> "Trace":
        trace = cls()
        for code, reasons in json.loads(blob or "{}").items():
            for reason, count in reasons.items():
                trace.note(code, reason, count)
        return trace

    def rows(self, league_code: str) -> list[tuple[str, int]]:
        """Reasons for one league, in funnel order, skipping the empty ones."""
        counts = self.counts[league_code]
        known = [(r, counts[r]) for r in self.ORDER if counts[r]]
        extra = [(r, n) for r, n in sorted(counts.items()) if r not in self.ORDER]
        return known + extra


def _price_line_key(quote: Quote) -> tuple:
    return (quote.market, quote.line)


def scan_fixture(
    conn: sqlite3.Connection,
    fixture: FixtureModel,
    settings=None,
    min_edge: float | None = None,
    as_of: str | None = None,
    trace: Trace | None = None,
) -> list[Candidate]:
    """Price up every market this fixture has odds for and keep the value."""
    settings = settings or load_settings()
    league = get_league(fixture.league_code)
    weight = confidence_weight(
        settings.market_blend(league.tier),
        fixture.matches_seen,
        float(settings.get("model.confidence_k", 8.0)),
    )
    min_edge = settings.get("selection.min_edge", 0.04) if min_edge is None else min_edge
    min_odds = float(settings.get("selection.min_odds", 1.4))
    max_odds = float(settings.get("selection.max_odds", 26.0))
    min_prob = float(settings.get("selection.min_model_prob", 0.05))
    min_prob_edge = float(settings.get("selection.min_prob_edge", 0.02))
    preferred = list(settings.get("bookmakers.preferred", []) or [])
    exchanges = list(settings.get("bookmakers.exchanges", []) or [])
    aggregates = list(settings.get("bookmakers.aggregates", []) or [])
    # Neither of these is somewhere you can place a bet: an exchange price is
    # the benchmark fair value is measured against, and "market max" is a
    # summary of a panel rather than a bookmaker.
    unbettable = set(exchanges) | set(aggregates)
    sharp = exchanges + aggregates + ["pinnacle"]
    max_edge = float(settings.get("selection.max_edge", 0.25))
    bankroll = float(settings.get("bankroll.starting_points", 100.0))
    kelly_frac = float(settings.get("bankroll.kelly_fraction", 0.25))
    max_stake = float(settings.get("bankroll.max_stake_pts", 3.0))
    min_stake = float(settings.get("bankroll.min_stake_pts", 0.25))
    step = float(settings.get("bankroll.stake_step", 0.25))

    groups = conn.execute(
        "SELECT DISTINCT market, line FROM odds WHERE match_id = ? AND is_closing = 0",
        (fixture.match_id,),
    ).fetchall()

    code = fixture.league_code

    def drop(reason: str, n: int = 1) -> None:
        if trace is not None:
            trace.note(code, reason, n)

    if not groups:
        # The case this whole tally exists for. A fixture nobody priced leaves
        # no market to iterate, so without this the league with the broken
        # feed is the one league the report says nothing about at all.
        drop("no price on file")

    out: list[Candidate] = []
    for group in groups:
        market, line = group["market"], group["line"]
        if market not in MODELLED_MARKETS:
            drop("market not modelled")
            continue
        quotes = latest_quotes(conn, fixture.match_id, market, line, as_of=as_of)
        if not quotes and as_of and fixture.kickoff > as_of:
            # Historical price files stamp the opening price with the match date
            # and nothing finer, so a strict "before the decision" cutoff throws
            # away every price for a fixture later in the week. Fall back to
            # prices stamped up to kickoff: still strictly pre-match, and the
            # closing line — the one that really would be cheating — is excluded
            # either way.
            quotes = latest_quotes(conn, fixture.match_id, market, line,
                                   as_of=fixture.kickoff)
        if not quotes:
            drop("no price on file")
            continue
        fair = consensus_fair(quotes, prefer_books=sharp)
        # Exchanges set the benchmark for what a price should be; they are not
        # the bet. Their margin is a fraction of a sportsbook's, so an exchange
        # is nearly always the "best price" — and it is also weighted as the
        # sharp reference when the fair price is calculated, so recommending one
        # measures a price against itself and calls the difference value. The
        # quoted price is pre-commission too.
        bettable = [q for q in quotes if q.bookmaker not in unbettable]
        if not bettable:
            drop("only unbettable prices (exchange or aggregate)")
            continue
        best = best_prices(bettable, preferred or None) or best_prices(bettable)

        for selection, quote in best.items():
            subject = None
            sel = selection
            if "|" in selection:
                subject, sel = selection.split("|", 1)
            model_prob = fixture.probability(market, sel, line, subject)
            if model_prob is None:
                drop("model has no view")
                continue
            if model_prob < min_prob:
                drop("model rates it below the floor")
                continue
            if not (min_odds <= quote.price <= max_odds):
                drop("price outside the odds limits")
                continue

            market_prob = fair.get(selection)
            blended = blend(model_prob, market_prob, weight)

            push_prob = 0.0
            if market == "ah" and line is not None:
                _, push_prob, _ = fixture.probs.asian_handicap(line, sel)
                # For a handicap the modelled probability is already the
                # break-even (push-excluded) number, so scale it back onto the
                # full market before working out the expected value.
                live = 1 - push_prob
                expected_value = blended * live * quote.price + push_prob - 1
            else:
                expected_value = blended * quote.price - 1

            if expected_value < min_edge:
                drop("edge below the minimum")
                continue
            if expected_value > max_edge:
                # An edge this size on a real market is almost always a fault in
                # the data — a mis-mapped line, a one-sided book, a stale price —
                # rather than value nobody else has noticed.
                drop("edge above the maximum (treated as a data fault)")
                continue
            # Expected value is a percentage of the stake, and that is not a
            # constant amount of evidence. At 1.50 a 4% edge means disagreeing
            # with the price by 2.7 points of probability; at 23.0 it means
            # disagreeing by 0.17 of a point, which is far inside the model's
            # own error. Left alone, that lets a rounding difference on a 4%
            # shot outbid a genuine read on a favourite, and the card fills up
            # with longshots. So demand the disagreement in probability too.
            # Dividing by the price converts the expected value back into
            # probability points, pushes included:
            #     EV / price = p_win - (1 - p_push) / price
            if expected_value / quote.price < min_prob_edge:
                drop("edge too thin in probability")
                continue

            fraction = kelly_fraction(
                blended * (1 - push_prob) if push_prob else blended,
                quote.price, push_prob,
            )
            stake = fraction * kelly_frac * bankroll
            stake = min(max_stake, round(stake / step) * step)
            if stake < min_stake:
                drop("stake rounds below the minimum")
                continue

            candidate = Candidate(
                fixture=fixture, market=market, selection=sel, line=line,
                price=quote.price, bookmaker=quote.bookmaker,
                model_prob=model_prob, market_prob=market_prob,
                blended_prob=blended, edge=expected_value, kelly=fraction,
                stake_pts=stake, push_prob=push_prob, subject=subject,
                books_seen=len({q.bookmaker for q in quotes}),
            )
            candidate.signals = candidate.supporting_signals()
            candidate.blend_weight = weight
            drop("priced up")
            out.append(candidate)

    out.sort(key=lambda c: -c.edge)
    return out
