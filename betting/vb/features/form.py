"""Signals: the things a tipster would actually say out loud.

The ratings model already knows who is good. What it does not say is *why*
this particular fixture is mispriced — a side who have been creating far more
than they have scored, a defence that has fallen apart over six weeks, a
striker missing, four days' less rest than the opposition, a price that has
been drifting all week.

Each of those is computed here as a :class:`Signal` with a direction, a
strength, and a sentence in plain English. They serve two purposes: they gate
selections (a bet needs supporting signals as well as an edge) and they supply
the write-up.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..models.xg import XgProxy, fit_proxy, match_xg
from ..repo import team_name

# A run whose most recent game is older than this is not "form" any more.
STALE_AFTER_DAYS = 45


def possessive(name: str) -> str:
    """Newcastle -> Newcastle's, Rangers -> Rangers'."""
    return f"{name}'" if name.endswith("s") else f"{name}'s"


@dataclass
class Signal:
    kind: str                # form | xg | news | rest | trend | market
    side: str                # home | away | match
    text: str                # tipster-ready sentence
    strength: float          # 0..1, how much weight it deserves
    favours: str = ""        # home | away | over | under | "" (neutral colour)
    # What the signal is actually about. A card-happy referee is no argument for
    # both teams to score, so a bet only quotes the signals on its own subject.
    topic: str = "result"    # result | goals | corners | cards

    def bullet(self) -> str:
        return self.text


@dataclass
class TeamForm:
    team_id: int
    name: str
    played: int
    points: int
    goals_for: int
    goals_against: int
    xg_for: float
    xg_against: float
    results: list[str]                 # most recent first, e.g. ["W","D","L"]
    btts_rate: float
    over25_rate: float
    clean_sheets: int
    failed_to_score: int
    corners_for: float
    corners_against: float
    cards_for: float
    xg_matches: int = 0            # how many of those games had usable xG
    days_since: int = 0            # age of the most recent game in the run
    current_season_games: int = 0  # how many of them are from this season

    @property
    def is_stale(self) -> bool:
        """True when the "form" predates the summer.

        On the opening weekend a club's last six games are from May, either
        side of a transfer window. Those results still carry information — the
        ratings model time-weights them — but calling them "recent form" in a
        write-up is misleading, so the signals say what they are.
        """
        return self.days_since > STALE_AFTER_DAYS or self.current_season_games == 0

    def run_phrase(self) -> str:
        """How to describe the run in prose, honestly."""
        if self.current_season_games == 0:
            return f"their last {self.played} of last season"
        if self.is_stale:
            return f"their last {self.played}, most of them last season"
        return f"their last {self.played}"

    @property
    def has_xg(self) -> bool:
        """True only when most of the run has an xG figure behind it.

        Some feeds carry goals and nothing else. Without shots there is no xG
        and no proxy for it, and a "goals versus xG" signal computed against a
        zero is worse than no signal at all.
        """
        return self.played > 0 and self.xg_matches >= max(3, self.played - 1)

    @property
    def points_per_game(self) -> float:
        return self.points / self.played if self.played else 0.0

    @property
    def xg_diff_per_game(self) -> float:
        return (self.xg_for - self.xg_against) / self.played if self.played else 0.0

    @property
    def finishing_gap(self) -> float:
        """Goals minus expected goals. Positive = running hot in front of goal."""
        return self.goals_for - self.xg_for

    @property
    def defensive_gap(self) -> float:
        """Goals conceded minus expected goals against. Positive = unlucky/poor keeping."""
        return self.goals_against - self.xg_against

    def form_string(self) -> str:
        return "".join(self.results[:6])


def recent_form(
    conn: sqlite3.Connection,
    team_id: int,
    league_code: str,
    before: datetime,
    games: int = 6,
    proxy: XgProxy | None = None,
) -> TeamForm | None:
    """Roll up a team's last ``games`` matches before ``before``."""
    proxy = proxy or fit_proxy(conn, league_code)
    rows = conn.execute(
        'SELECT kickoff, season, home_id, away_id, fthg, ftag, hs, "as", hst, ast, hc, ac, '
        "hy, ay, home_xg, away_xg FROM matches WHERE league_code = ? AND status = 'played' "
        "AND (home_id = ? OR away_id = ?) AND kickoff < ? ORDER BY kickoff DESC LIMIT ?",
        (league_code, team_id, team_id, before.isoformat(), games),
    ).fetchall()
    if not rows:
        return None

    points = goals_for = goals_against = clean = failed = 0
    xg_for = xg_against = corners_for = corners_against = cards = 0.0
    btts = over25 = xg_matches = 0
    results: list[str] = []
    for r in rows:
        home = r["home_id"] == team_id
        scored = r["fthg"] if home else r["ftag"]
        conceded = r["ftag"] if home else r["fthg"]
        goals_for += scored
        goals_against += conceded
        if scored > conceded:
            points += 3
            results.append("W")
        elif scored == conceded:
            points += 1
            results.append("D")
        else:
            results.append("L")
        clean += 1 if conceded == 0 else 0
        failed += 1 if scored == 0 else 0
        btts += 1 if (r["fthg"] > 0 and r["ftag"] > 0) else 0
        over25 += 1 if (r["fthg"] + r["ftag"]) > 2.5 else 0
        home_xg, away_xg = match_xg(r, proxy)
        if home_xg is not None and away_xg is not None:
            xg_for += home_xg if home else away_xg
            xg_against += away_xg if home else home_xg
            xg_matches += 1
        corners_for += (r["hc"] if home else r["ac"]) or 0
        corners_against += (r["ac"] if home else r["hc"]) or 0
        cards += (r["hy"] if home else r["ay"]) or 0

    played = len(rows)
    try:
        days_since = max(0, (before - datetime.fromisoformat(rows[0]["kickoff"][:19])).days)
    except ValueError:
        days_since = 0
    latest_season = rows[0]["season"]
    current_season_games = sum(1 for r in rows if r["season"] == latest_season
                               and days_since <= STALE_AFTER_DAYS)
    return TeamForm(
        team_id=team_id, name=team_name(conn, team_id), played=played,
        points=points, goals_for=goals_for, goals_against=goals_against,
        xg_for=xg_for, xg_against=xg_against, results=results,
        btts_rate=btts / played, over25_rate=over25 / played,
        clean_sheets=clean, failed_to_score=failed,
        corners_for=corners_for / played, corners_against=corners_against / played,
        cards_for=cards / played, xg_matches=xg_matches,
        days_since=days_since, current_season_games=current_season_games,
    )


def rest_days(conn: sqlite3.Connection, team_id: int, before: datetime) -> tuple[int, int]:
    """(days since the last match, matches played in the previous fortnight)."""
    row = conn.execute(
        "SELECT kickoff FROM matches WHERE (home_id = ? OR away_id = ?) "
        "AND status = 'played' AND kickoff < ? ORDER BY kickoff DESC LIMIT 1",
        (team_id, team_id, before.isoformat()),
    ).fetchone()
    if not row:
        return (14, 0)
    try:
        days = (before - datetime.fromisoformat(row["kickoff"][:19])).days
    except ValueError:
        days = 7
    congestion = conn.execute(
        "SELECT COUNT(*) AS n FROM matches WHERE (home_id = ? OR away_id = ?) "
        "AND status = 'played' AND kickoff BETWEEN ? AND ?",
        (team_id, team_id, (before - timedelta(days=14)).isoformat(), before.isoformat()),
    ).fetchone()["n"]
    return (max(0, days), int(congestion))


def team_news(conn: sqlite3.Connection, team_id: int, before: datetime,
              window_days: int = 14, match_id: int | None = None) -> list[sqlite3.Row]:
    """Absences relevant to one fixture.

    News pinned to a specific match applies to that match only — a one-game
    suspension should not follow a club around for a fortnight. News with no
    match attached is general, and applies for a window.
    """
    since = (before - timedelta(days=window_days)).date().isoformat()
    return conn.execute(
        "SELECT * FROM team_news WHERE team_id = ? "
        "AND ((match_id IS NULL AND added_at >= ?) OR match_id = ?) "
        "ORDER BY impact DESC",
        (team_id, since, match_id),
    ).fetchall()


def news_impact(rows: list[sqlite3.Row]) -> float:
    """Total share of team strength missing. Capped — a squad is never zero."""
    total = sum(float(r["impact"] or 0.0) for r in rows)
    return max(-0.25, min(0.45, total))


def market_drift(conn: sqlite3.Connection, match_id: int, market: str = "h2h",
                 selection: str = "home") -> float | None:
    """Fractional move between the first and latest price seen. Negative = shortening."""
    rows = conn.execute(
        "SELECT price, taken_at FROM odds WHERE match_id = ? AND market = ? "
        "AND selection = ? AND is_closing = 0 ORDER BY taken_at",
        (match_id, market, selection),
    ).fetchall()
    if len(rows) < 2:
        return None
    first, last = float(rows[0]["price"]), float(rows[-1]["price"])
    if first <= 1.0:
        return None
    return (last - first) / first


# ---------------------------------------------------------------------------
# turning the numbers into sentences
# ---------------------------------------------------------------------------
def build_signals(
    conn: sqlite3.Connection,
    match: sqlite3.Row,
    league_code: str,
    proxy: XgProxy | None = None,
) -> list[Signal]:
    """Everything worth saying about one upcoming fixture."""
    kickoff = datetime.fromisoformat(match["kickoff"][:19])
    home_id, away_id = match["home_id"], match["away_id"]
    proxy = proxy or fit_proxy(conn, league_code)
    home = recent_form(conn, home_id, league_code, kickoff, proxy=proxy)
    away = recent_form(conn, away_id, league_code, kickoff, proxy=proxy)
    signals: list[Signal] = []
    if not home or not away:
        return signals

    # --- form ---------------------------------------------------------------
    for side, form in (("home", home), ("away", away)):
        if form.played >= 4:
            ppg = form.points_per_game
            stale = 0.45 if form.is_stale else 1.0
            if ppg >= 2.0:
                signals.append(Signal(
                    "form", side,
                    f"{form.name} took {form.points} points from "
                    f"{form.run_phrase()} ({form.form_string()})",
                    min(1.0, (ppg - 1.3) / 1.0) * stale, favours=side,
                ))
            elif ppg <= 0.8:
                signals.append(Signal(
                    "form", side,
                    f"{form.name} managed just {form.points} points from "
                    f"{form.run_phrase()} ({form.form_string()})",
                    min(1.0, (1.1 - ppg) / 1.0) * stale,
                    favours="away" if side == "home" else "home",
                ))

    # --- xG versus results --------------------------------------------------
    # Only where the league actually has the shot data to compute it.
    for side, form in (("home", home), ("away", away)):
        if not form.has_xg:
            continue
        gap = form.finishing_gap
        if form.played >= 5 and gap <= -2.0:
            signals.append(Signal(
                "xg", side,
                f"{form.name} have created plenty and finished none of it — "
                f"{form.goals_for} goals from {form.xg_for:.1f} xG in {form.played} games, "
                "which usually corrects",
                min(1.0, abs(gap) / 4.0), favours=side,
            ))
        elif form.played >= 5 and gap >= 2.5:
            signals.append(Signal(
                "xg", side,
                f"{form.name} are running hot: {form.goals_for} goals from only "
                f"{form.xg_for:.1f} xG, and that finishing rate is not a thing you can bank on",
                min(1.0, gap / 4.0),
                favours="away" if side == "home" else "home",
            ))
        defensive = form.defensive_gap
        if form.played >= 5 and defensive >= 2.5:
            signals.append(Signal(
                "xg", side,
                f"{form.name} have shipped {form.goals_against} from "
                f"{form.xg_against:.1f} xG against — the defence is not as bad as the column says",
                min(1.0, defensive / 4.0), favours=side,
            ))

    home_xgd, away_xgd = home.xg_diff_per_game, away.xg_diff_per_game
    if home.has_xg and away.has_xg and abs(home_xgd - away_xgd) > 0.6:
        better, worse = (home, away) if home_xgd > away_xgd else (away, home)
        side = "home" if better is home else "away"
        signals.append(Signal(
            "xg", side,
            f"On the underlying numbers it is not close: {better.name} are running at "
            f"{max(home_xgd, away_xgd):+.2f} xG per game over this run against "
            f"{possessive(worse.name)} {min(home_xgd, away_xgd):+.2f}",
            min(1.0, abs(home_xgd - away_xgd) / 1.5), favours=side,
        ))

    # --- goals character ----------------------------------------------------
    stale_run = home.is_stale or away.is_stale
    stale_factor = 0.45 if stale_run else 1.0
    when = " games last season" if stale_run else " games"
    combined_over = (home.over25_rate + away.over25_rate) / 2
    if combined_over >= 0.75:
        signals.append(Signal(
            "trend", "match",
            f"Over 2.5 landed in {home.over25_rate:.0%} of {possessive(home.name)} and "
            f"{away.over25_rate:.0%} of {possessive(away.name)} last six{when}",
            min(1.0, (combined_over - 0.5) * 2) * stale_factor, favours="over",
            topic="goals",
        ))
    elif combined_over <= 0.3:
        signals.append(Signal(
            "trend", "match",
            f"Low-scoring fare all round — over 2.5 landed in only "
            f"{home.over25_rate:.0%} and {away.over25_rate:.0%} of their last six{when}",
            min(1.0, (0.5 - combined_over) * 2) * stale_factor, favours="under",
            topic="goals",
        ))

    combined_btts = (home.btts_rate + away.btts_rate) / 2
    if combined_btts >= 0.75:
        signals.append(Signal(
            "trend", "match",
            f"Both teams scored in {home.btts_rate:.0%} of {possessive(home.name)} and "
            f"{away.btts_rate:.0%} of {possessive(away.name)} last six{when}",
            min(1.0, (combined_btts - 0.5) * 2) * stale_factor, favours="over",
            topic="goals",
        ))
    if home.clean_sheets >= 3 or away.clean_sheets >= 3:
        keeper = home if home.clean_sheets >= away.clean_sheets else away
        signals.append(Signal(
            "trend", "home" if keeper is home else "away",
            f"{keeper.name} have kept {keeper.clean_sheets} clean sheets in their last "
            f"{keeper.played}",
            0.5, favours="under", topic="goals",
        ))

    # --- rest and congestion -------------------------------------------------
    home_rest, home_games = rest_days(conn, home_id, kickoff)
    away_rest, away_games = rest_days(conn, away_id, kickoff)
    if abs(home_rest - away_rest) >= 3:
        fresher = "home" if home_rest > away_rest else "away"
        fresh_name = home.name if fresher == "home" else away.name
        tired_name = away.name if fresher == "home" else home.name
        signals.append(Signal(
            "rest", fresher,
            f"{fresh_name} have had {max(home_rest, away_rest)} days since their last game, "
            f"{tired_name} only {min(home_rest, away_rest)}",
            min(1.0, abs(home_rest - away_rest) / 6.0), favours=fresher,
        ))
    for side, games, name in (("home", home_games, home.name), ("away", away_games, away.name)):
        if games >= 4:
            signals.append(Signal(
                "rest", side,
                f"{name} are into a fourth game in a fortnight and legs will be heavy",
                0.45, favours="away" if side == "home" else "home",
            ))

    # --- team news -----------------------------------------------------------
    for side, team_id_ in (("home", home_id), ("away", away_id)):
        rows = team_news(conn, team_id_, kickoff, match_id=match["id"])
        if not rows:
            continue
        impact = news_impact(rows)
        names = ", ".join(r["player"] for r in rows[:3])
        kinds = {r["kind"] for r in rows}
        if impact >= 0.08:
            verb = "are without" if "suspension" in kinds or "injury" in kinds else "are missing"
            signals.append(Signal(
                "news", side,
                f"{(home if side == 'home' else away).name} {verb} {names}"
                + (f" and {len(rows) - 3} more" if len(rows) > 3 else ""),
                min(1.0, impact * 3),
                favours="away" if side == "home" else "home",
            ))
        elif impact <= -0.05:
            signals.append(Signal(
                "news", side,
                f"{(home if side == 'home' else away).name} welcome back {names}",
                min(1.0, abs(impact) * 3), favours=side,
            ))

    # --- corners and cards ---------------------------------------------------
    corner_total = home.corners_for + away.corners_against
    if corner_total >= 12.5:
        signals.append(Signal(
            "trend", "home",
            f"{home.name} have averaged {home.corners_for:.1f} corners a game and "
            f"{away.name} have conceded {away.corners_against:.1f}",
            0.5, favours="over", topic="corners",
        ))
    if (home.cards_for + away.cards_for) >= 5.0:
        signals.append(Signal(
            "trend", "match",
            f"Both sides collect cards — {home.cards_for:.1f} and {away.cards_for:.1f} "
            "yellows a game between them",
            0.45, favours="over", topic="cards",
        ))

    # --- market movement ------------------------------------------------------
    for selection, side in (("home", "home"), ("away", "away")):
        drift = market_drift(conn, match["id"], "h2h", selection)
        if drift is not None and drift <= -0.06:
            signals.append(Signal(
                "market", side,
                f"The {(home if side == 'home' else away).name} price has been shortening "
                f"all week ({abs(drift):.0%})",
                min(1.0, abs(drift) * 6), favours=side,
            ))
        elif drift is not None and drift >= 0.08:
            signals.append(Signal(
                "market", side,
                f"{(home if side == 'home' else away).name} have drifted {drift:.0%} "
                "in the market, which is rarely an accident",
                min(1.0, drift * 5),
                favours="away" if side == "home" else "home",
            ))

    return signals


def supporting(signals: list[Signal], favours: str) -> list[Signal]:
    """The signals that back a given side or direction."""
    return [s for s in signals if s.favours == favours]
