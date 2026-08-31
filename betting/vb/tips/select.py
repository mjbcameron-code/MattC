"""Choosing the week's bets and writing them up.

The engine will happily find two hundred prices with a positive expectation.
Most of them should not be bet: the edge is inside the noise, or nothing about
the fixture supports the number, or it is the fourth bet on the same match.
This module applies the discipline — supporting evidence, one angle per match,
a cap per league, a cap per week — and then hands the survivors to the
write-up.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..config import league as get_league, load_settings
from ..market.value import Candidate, Trace, scan_fixture
from ..models.fixture import FixtureModel, ModelBank, build_fixture
from ..models.season import simulate_season
from ..models.simulate import Leg, combined_probability, correlation_factor
from . import language

# Markets that are really the same opinion wearing a different hat — we only
# want one of them per match.
MARKET_FAMILY = {
    "h2h": "result", "ah": "result", "dnb": "result", "double_chance": "result",
    "correct_score": "result",
    "totals": "goals", "btts": "goals", "team_totals": "goals",
    "clean_sheet": "goals",
    "corners": "corners",
    "cards": "cards", "booking_points": "cards",
    "player_sot": "players", "player_shots": "players",
    "player_card": "players", "player_goal": "players",
}


@dataclass
class Tip:
    ref: str
    kind: str                       # single | acca | builder | outright
    headline: str
    body: str
    selection: str
    market: str
    league_code: str
    event_date: str
    price: float
    stake_pts: float
    model_prob: float
    edge: float
    confidence: int
    bookmaker: str = ""
    fair_prob: float | None = None
    match_id: int | None = None
    fixture: str = ""
    signals: list[str] = field(default_factory=list)
    legs: list[dict] = field(default_factory=list)
    target_price: float | None = None
    # The machine-readable form of the selection, kept alongside the human one
    # so that settlement can grade the bet without parsing English.
    raw_market: str = ""
    raw_selection: str = ""
    raw_line: float | None = None
    subject: str | None = None

    @property
    def fair_price(self) -> float:
        return 1 / self.model_prob if self.model_prob else float("inf")

    @property
    def stars(self) -> str:
        return language.stars(self.confidence)


@dataclass
class TipSheet:
    generated_at: str
    week_ref: str
    bet_of_the_week: Tip | None
    singles: list[Tip] = field(default_factory=list)
    accumulators: list[Tip] = field(default_factory=list)
    builders: list[Tip] = field(default_factory=list)
    outrights: list[Tip] = field(default_factory=list)
    fixtures_scanned: int = 0
    candidates_found: int = 0

    @property
    def all_tips(self) -> list[Tip]:
        tips = list(self.singles) + self.accumulators + self.builders + self.outrights
        return tips

    @property
    def total_stake(self) -> float:
        return sum(t.stake_pts for t in self.all_tips)


def week_reference(when: datetime) -> str:
    iso = when.isocalendar()
    return f"{iso.year}W{iso.week:02d}"


def _score(candidate: Candidate) -> float:
    """Ranking score: edge, weighted by how much evidence backs it."""
    support = sum(s.strength for s in candidate.supporting_signals())
    return candidate.edge * (1.0 + min(1.0, support / 2.0)) * (0.85 + 0.03 * candidate.confidence())


def gather(
    conn: sqlite3.Connection,
    days: int = 7,
    leagues: list[str] | None = None,
    as_of: datetime | None = None,
    with_players: bool = True,
    statuses: tuple[str, ...] = ("scheduled",),
    trace: Trace | None = None,
) -> tuple[list[Candidate], dict[int, FixtureModel], ModelBank]:
    """Price up every fixture in the window and return everything with an edge.

    ``statuses`` is normally just "scheduled". A backtest passes "played"
    instead, so that already-finished matches are treated as if they were still
    to come — with every model refitted, and every price read, as of the
    decision date rather than today.
    """
    as_of = as_of or datetime.now()
    end = as_of + timedelta(days=days)
    placeholders = ",".join("?" * len(statuses))
    sql = (f"SELECT * FROM matches WHERE status IN ({placeholders}) "
           "AND kickoff >= ? AND kickoff <= ?")
    params: list = [*statuses, as_of.isoformat(), end.isoformat()]
    if leagues:
        sql += f" AND league_code IN ({','.join('?' * len(leagues))})"
        params += leagues
    rows = conn.execute(sql + " ORDER BY kickoff", params).fetchall()

    bank = ModelBank(conn, as_of=as_of)
    candidates: list[Candidate] = []
    fixtures: dict[int, FixtureModel] = {}
    for row in rows:
        fixture = build_fixture(conn, row, bank, with_players=with_players)
        if fixture is None:
            if trace is not None:
                trace.note(row["league_code"], "no model for this fixture")
            continue
        fixtures[fixture.match_id] = fixture
        candidates.extend(
            scan_fixture(conn, fixture, as_of=as_of.isoformat(), trace=trace))
    return candidates, fixtures, bank


def _passes_evidence(candidate: Candidate, min_signals: int) -> bool:
    support = candidate.supporting_signals()
    if len(support) >= min_signals:
        return True
    # A very strong single signal counts double.
    return sum(1 for s in support if s.strength >= 0.75) * 2 >= min_signals


def choose_singles(candidates: list[Candidate], settings=None,
                   trace: Trace | None = None) -> list[Candidate]:
    """Apply the discipline: evidence, one angle per match, caps."""
    settings = settings or load_settings()
    min_signals = int(settings.get("selection.min_signals", 2))
    # "Fancied for good reason" is the whole basis for allowing a longshot at
    # all, so the reason has to be there. A price beyond max_odds is where the
    # model's probability is least reliable — a fraction of a point of error
    # moves the edge enormously — and corroborating signals are the only
    # independent check the engine has on it.
    long_signals = int(settings.get("selection.longshots.min_signals", 3))
    max_tips = int(settings.get("selection.max_tips_per_week", 12))
    max_per_league = int(settings.get("selection.max_tips_per_league", 3))

    eligible = []
    for candidate in candidates:
        needed = long_signals if candidate.longshot else min_signals
        if _passes_evidence(candidate, needed):
            eligible.append(candidate)
        elif trace is not None:
            trace.note(candidate.league_code,
                       "longshot without enough corroboration"
                       if candidate.longshot else "not enough supporting signals")
    eligible.sort(key=_score, reverse=True)

    chosen: list[Candidate] = []
    per_league: dict[str, int] = {}
    seen_family: set[tuple[int, str]] = set()
    seen_match: dict[int, int] = {}
    for candidate in eligible:
        league_code = candidate.league_code
        family = MARKET_FAMILY.get(candidate.market, candidate.market)
        key = (candidate.fixture.match_id, family)
        if key in seen_family:
            if trace is not None:
                trace.note(league_code, "same angle already taken")
            continue
        if seen_match.get(candidate.fixture.match_id, 0) >= 2:
            if trace is not None:
                trace.note(league_code, "two bets on that match already")
            continue
        if per_league.get(league_code, 0) >= max_per_league:
            if trace is not None:
                trace.note(league_code, "league is already at its cap")
            continue
        chosen.append(candidate)
        if trace is not None:
            trace.note(league_code, "tipped")
        seen_family.add(key)
        seen_match[candidate.fixture.match_id] = seen_match.get(candidate.fixture.match_id, 0) + 1
        per_league[league_code] = per_league.get(league_code, 0) + 1
        if len(chosen) >= max_tips:
            break
    return chosen


def _candidate_to_tip(candidate: Candidate, ref: str, prefix: str = "") -> Tip:
    league = get_league(candidate.league_code)
    headline, body = language.write_single(
        ref=ref,
        selection=candidate.selection_text(),
        fixture_label=candidate.fixture.label,
        competition=league.name,
        price=candidate.price,
        book=candidate.bookmaker,
        stake=candidate.stake_pts,
        fair_price=1 / candidate.blended_prob if candidate.blended_prob else 0.0,
        edge=candidate.edge,
        signals=candidate.supporting_signals(),
        confidence=candidate.confidence(),
        headline_prefix=prefix,
    )
    return Tip(
        ref=ref, kind="single",
        headline=f"{candidate.fixture.label} — {headline}",
        body=body,
        selection=candidate.selection_text(),
        market=candidate.market_label,
        league_code=candidate.league_code,
        event_date=candidate.fixture.kickoff[:10],
        price=candidate.price, stake_pts=candidate.stake_pts,
        model_prob=candidate.blended_prob, edge=candidate.edge,
        confidence=candidate.confidence(), bookmaker=candidate.bookmaker,
        fair_prob=candidate.market_prob, match_id=candidate.fixture.match_id,
        fixture=candidate.fixture.label,
        signals=[s.text for s in candidate.supporting_signals()[:4]],
        raw_market=candidate.market, raw_selection=candidate.selection,
        raw_line=candidate.line, subject=candidate.subject,
    )


# ---------------------------------------------------------------------------
# accumulators
# ---------------------------------------------------------------------------
def build_accumulators(candidates: list[Candidate], settings=None,
                       ref_prefix: str = "ACC") -> list[Tip]:
    settings = settings or load_settings()
    if not settings.get("accumulator.enabled", True):
        return []
    min_legs = int(settings.get("accumulator.min_legs", 2))
    max_legs = int(settings.get("accumulator.max_legs", 4))
    min_leg_prob = float(settings.get("accumulator.min_leg_prob", 0.45))
    min_edge = float(settings.get("accumulator.min_combined_edge", 0.10))
    max_stake = float(settings.get("accumulator.max_stake_pts", 1.0))
    haircut = float(settings.get("accumulator.leg_haircut", 0.04))

    pool = [c for c in candidates
            if c.blended_prob >= min_leg_prob and c.edge > 0.02]
    pool.sort(key=_score, reverse=True)

    # One leg per match, best first.
    legs: list[Candidate] = []
    used: set[int] = set()
    for candidate in pool:
        if candidate.fixture.match_id in used:
            continue
        legs.append(candidate)
        used.add(candidate.fixture.match_id)
        if len(legs) >= max_legs:
            break
    if len(legs) < min_legs:
        return []

    tips: list[Tip] = []
    for size in range(min_legs, len(legs) + 1):
        if size > max_legs:
            break
        selection = legs[:size]
        price = 1.0
        prob = 1.0
        for leg in selection:
            price *= leg.price
            # Each leg is discounted before folding. A single bet can carry the
            # model being a little wrong; a four-fold multiplies that error four
            # times over, and an accumulator built from four optimistic
            # estimates is how a good model produces a bad bet.
            prob *= leg.blended_prob * (1 - haircut)
        edge = prob * price - 1
        if edge < min_edge:
            continue
        ref = f"{ref_prefix}-{size}"
        leg_dicts = [{
            "fixture": leg.fixture.label,
            "selection": leg.selection_text(),
            "price": leg.price,
            "book": leg.bookmaker,
            "model_prob": leg.blended_prob,
            "match_id": leg.fixture.match_id,
            "market": leg.market,
            "raw_selection": leg.selection,
            "line": leg.line,
        } for leg in selection]
        headline, body = language.write_accumulator(
            ref, leg_dicts, price, max_stake, 1 / prob if prob else 0.0, edge)
        tips.append(Tip(
            ref=ref, kind="acca", headline=headline, body=body,
            selection=" + ".join(
                f"{leg['selection']} ({leg['fixture']})" for leg in leg_dicts),
            market="Accumulator",
            league_code=selection[0].league_code,
            event_date=max(leg.fixture.kickoff[:10] for leg in selection),
            price=round(price, 2), stake_pts=max_stake, model_prob=prob,
            edge=edge, confidence=min(4, max(1, int(2 + edge * 8))),
            bookmaker=selection[0].bookmaker, legs=leg_dicts,
        ))
    # Keep the best-value fold only.
    tips.sort(key=lambda t: -t.edge)
    return tips[:1]


# ---------------------------------------------------------------------------
# bet builders
# ---------------------------------------------------------------------------
BUILDER_TEMPLATES = [
    # (market, selection, line) with the direction the signals must support
    ("result+goals", [("h2h", "{side}", None), ("totals", "over", 2.5)], "over"),
    ("result+goals", [("h2h", "{side}", None), ("totals", "under", 2.5)], "under"),
    ("goals+corners", [("totals", "over", 2.5), ("corners", "over", 9.5)], "over"),
    ("result+btts", [("h2h", "{side}", None), ("btts", "yes", None)], "over"),
    ("result+cards", [("h2h", "{side}", None), ("cards", "over", 3.5)], "over"),
]


def _anchor_to_market(conn, fixture, market, selection, line, model_prob,
                      blend_weight, as_of_iso):
    """Blend one leg's model probability with the market's, where the market has one."""
    from ..market.odds import consensus_fair, latest_quotes
    from ..market.value import blend

    quotes = latest_quotes(conn, fixture.match_id, market, line, as_of=as_of_iso)
    if not quotes:
        return model_prob
    fair = consensus_fair(quotes)
    return blend(model_prob, fair.get(selection), blend_weight)


def build_builders(
    conn: sqlite3.Connection,
    fixtures: dict[int, FixtureModel],
    candidates: list[Candidate],
    settings=None,
    limit: int = 2,
    ref_prefix: str = "BB",
    as_of: datetime | None = None,
) -> list[Tip]:
    """Correlation-aware same-game combinations, quoted as a target price."""
    settings = settings or load_settings()
    if not settings.get("bet_builder.enabled", True):
        return []
    sims = int(settings.get("bet_builder.simulations", 40000))
    min_edge = float(settings.get("bet_builder.min_combined_edge", 0.12))
    max_stake = float(settings.get("bet_builder.max_stake_pts", 1.0))
    max_legs = int(settings.get("bet_builder.max_legs", 4))
    haircut = float(settings.get("bet_builder.leg_haircut", 0.04))
    as_of_iso = (as_of or datetime.now()).isoformat()

    # Only build on fixtures we already like for a reason.
    by_match: dict[int, list[Candidate]] = {}
    for candidate in candidates:
        by_match.setdefault(candidate.fixture.match_id, []).append(candidate)

    ranked = sorted(
        by_match.items(),
        key=lambda kv: -max(_score(c) for c in kv[1]),
    )

    tips: list[Tip] = []
    for match_id, match_candidates in ranked:
        if len(tips) >= limit:
            break
        fixture = fixtures.get(match_id)
        if fixture is None:
            continue
        best = max(match_candidates, key=_score)
        blend_weight = best.blend_weight
        side = best.favours()
        if side not in ("home", "away", "over", "under"):
            continue
        directions = {s.favours for s in fixture.signals if s.strength >= 0.4}

        for _, template, needs in BUILDER_TEMPLATES:
            if needs not in directions and needs not in (side,):
                continue
            legs: list[Leg] = []
            marginals: list[float] = []
            ok = True
            for market, selection, line in template:
                sel = selection.format(side=side if side in ("home", "away") else "home")
                prob = fixture.probability(market, sel, line)
                if prob is None or prob <= 0.05:
                    ok = False
                    break
                # Price the leg exactly as a single would be priced: anchored to
                # the market where a price exists. Building a combination out of
                # unanchored model numbers compounds the model's optimism once
                # per leg, which is how a builder that looks like value is not.
                prob = _anchor_to_market(conn, fixture, market, sel, line, prob,
                                         blend_weight, as_of_iso)
                # Shade each leg, exactly as an accumulator does. The backtest
                # is unambiguous about why: over two seasons the model
                # over-predicts in every probability band, and that error
                # compounds once per leg. Accumulators, which shade, came out
                # ahead; builders, which did not, lost a quarter of everything
                # staked on them and carried 87% of the total loss from 26% of
                # the money. A leg is not more reliable for having been chosen
                # by a template rather than by the value engine — it is less.
                prob = max(0.01, prob - haircut)
                legs.append(Leg(market, sel, line))
                marginals.append(prob)
            if not ok or len(legs) < 2 or len(legs) > max_legs:
                continue

            sim = fixture.simulate(n=sims, seed=match_id)
            joint = combined_probability(sim, legs, marginals)
            if joint <= 0.02:
                continue
            factor = correlation_factor(sim, legs)
            fair_price = 1 / joint
            target_price = fair_price * (1 + min_edge)

            leg_dicts = []
            for leg, prob in zip(legs, marginals):
                temp = Candidate(
                    fixture=fixture, market=leg.market, selection=leg.selection,
                    line=leg.line, price=1 / prob, bookmaker="", model_prob=prob,
                    market_prob=None, blended_prob=prob, edge=0.0, kelly=0.0,
                    stake_pts=0.0,
                )
                leg_dicts.append({
                    "fixture": fixture.label,
                    "selection": temp.selection_text(),
                    "market": leg.market,
                    "raw_selection": leg.selection,
                    "line": leg.line,
                    "model_prob": prob,
                    "price": round(1 / prob, 2),
                    "match_id": match_id,
                })
            ref = f"{ref_prefix}-{match_id}"
            headline, body = language.write_builder(
                ref, fixture.label, leg_dicts, fair_price, target_price,
                max_stake, factor, fixture.signals,
            )
            tips.append(Tip(
                ref=ref, kind="builder", headline=headline, body=body,
                selection=" & ".join(leg["selection"] for leg in leg_dicts),
                market="Bet builder", league_code=fixture.league_code,
                event_date=fixture.kickoff[:10],
                price=round(target_price, 2), stake_pts=max_stake,
                model_prob=joint, edge=min_edge,
                confidence=min(4, max(2, int(1 + len(fixture.signals) / 2))),
                match_id=match_id, fixture=fixture.label, legs=leg_dicts,
                target_price=round(target_price, 2),
                signals=[s.text for s in fixture.signals[:3]],
            ))
            break
    return tips


# ---------------------------------------------------------------------------
# long-term / outright markets
# ---------------------------------------------------------------------------
OUTRIGHT_LABELS = {
    "winner": "outright winner", "title": "title", "top_four": "top four",
    "top_two": "automatic promotion", "top_six": "top six",
    "relegation": "relegation", "top_half": "top half",
}


def build_outrights(
    conn: sqlite3.Connection,
    bank: ModelBank,
    season: str,
    leagues: list[str] | None = None,
    settings=None,
    simulations: int = 8000,
    ref_prefix: str = "LT",
) -> list[Tip]:
    """Value in the season-long markets, where prices have been entered."""
    settings = settings or load_settings()
    if not settings.get("long_term.enabled", True):
        return []
    min_edge = float(settings.get("long_term.min_edge", 0.10))
    min_prob_edge = float(settings.get("long_term.min_prob_edge", 0.03))
    max_stake = float(settings.get("long_term.max_stake_pts", 2.0))

    rows = conn.execute(
        "SELECT DISTINCT league_code FROM outright_odds WHERE season = ?", (season,)
    ).fetchall()
    codes = [r["league_code"] for r in rows]
    if leagues:
        codes = [c for c in codes if c in leagues]
    tips: list[Tip] = []
    for code in codes:
        model = bank.ratings(code)
        if model is None:
            continue
        outlook = simulate_season(conn, model, season, simulations=simulations, seed=11)
        if outlook is None:
            continue
        priced = conn.execute(
            "SELECT market, selection, bookmaker, MAX(price) AS price FROM outright_odds "
            "WHERE league_code = ? AND season = ? GROUP BY market, selection",
            (code, season),
        ).fetchall()
        for row in priced:
            from ..repo import resolve_team

            team_id = resolve_team(conn, row["selection"], code, create=False)
            if team_id is None:
                continue
            prob = outlook.probability(row["market"], team_id)
            if prob is None or prob <= 0.01:
                continue
            price = float(row["price"])
            edge = prob * price - 1
            if edge < min_edge:
                continue
            # And beat the price in probability, not just as a share of the
            # stake — otherwise a rounding difference on a 100/1 shot reads as
            # a bigger edge than a real call on the title favourite.
            if edge / price < min_prob_edge:
                continue
            stake = min(max_stake, max(0.25, round(edge * 4 * 4) / 4))
            label = OUTRIGHT_LABELS.get(row["market"], row["market"].replace("_", " "))
            detail = (
                f"Playing the season out {outlook.simulations:,} times from the "
                f"current table, {outlook.teams.get(team_id, row['selection'])} land "
                f"it {prob:.0%} of the time — they are on "
                f"{outlook.current_points.get(team_id, 0)} points with an expected "
                f"finish of {outlook.expected_points.get(team_id, 0):.0f}."
            )
            ref = f"{ref_prefix}-{code}-{team_id}-{row['market']}"
            headline, body = language.write_outright(
                ref, outlook.teams.get(team_id, row["selection"]), label,
                get_league(code).name, price, row["bookmaker"], stake,
                1 / prob, edge, detail,
            )
            tips.append(Tip(
                ref=ref, kind="outright", headline=headline, body=body,
                selection=f"{outlook.teams.get(team_id, row['selection'])} — {label}",
                market=f"Outright: {label}", league_code=code,
                event_date=_season_end(season), price=price, stake_pts=stake,
                model_prob=prob, edge=edge,
                confidence=min(5, max(1, int(2 + edge * 5))),
                bookmaker=row["bookmaker"],
            ))
    tips.sort(key=lambda t: -t.edge)
    return tips[:3]


def _season_end(season: str) -> str:
    end = season.split("/")[-1]
    year = int(end) + 2000 if len(end) == 2 else int(end)
    return f"{year}-05-31"


# ---------------------------------------------------------------------------
# the whole sheet
# ---------------------------------------------------------------------------
def build_tipsheet(
    conn: sqlite3.Connection,
    days: int = 7,
    leagues: list[str] | None = None,
    as_of: datetime | None = None,
    season: str | None = None,
    include_outrights: bool = True,
    statuses: tuple[str, ...] = ("scheduled",),
    trace: Trace | None = None,
) -> TipSheet:
    as_of = as_of or datetime.now()
    settings = load_settings()
    season = season or settings.get("report.season", "2025/26")
    week = week_reference(as_of)

    candidates, fixtures, bank = gather(conn, days=days, leagues=leagues,
                                        as_of=as_of, statuses=statuses,
                                        trace=trace)
    chosen = choose_singles(candidates, settings, trace=trace)

    singles: list[Tip] = []
    for i, candidate in enumerate(chosen, start=1):
        ref = f"{week}-{i:02d}"
        singles.append(_candidate_to_tip(candidate, ref))

    sheet = TipSheet(
        generated_at=as_of.isoformat(timespec="seconds"),
        week_ref=week,
        bet_of_the_week=None,
        singles=singles,
        fixtures_scanned=len(fixtures),
        candidates_found=len(candidates),
    )
    if singles:
        best = singles[0]
        best.headline = language.bet_of_the_week(best.headline)
        sheet.bet_of_the_week = best

    sheet.accumulators = build_accumulators(chosen or candidates, settings,
                                            ref_prefix=f"{week}-ACC")
    sheet.builders = build_builders(conn, fixtures, candidates, settings,
                                    ref_prefix=f"{week}-BB", as_of=as_of)
    if include_outrights:
        sheet.outrights = build_outrights(conn, bank, season, leagues, settings,
                                          ref_prefix=f"{week}-LT")
    return sheet
