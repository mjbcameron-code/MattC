"""Grading bets against results, and measuring them against the closing line.

Two numbers come out of here. The obvious one is profit and loss in points.
The one that matters sooner is closing line value: whether the price we advised
was better than the price the market finished at. Profit over twenty bets is
mostly noise; beating the close over twenty bets is not, and a tipster who
consistently beats the close will be in front eventually.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from ..config import load_settings


# The value of one settled leg, as a multiple of the stake on it.
MULTIPLIERS = {"won": None, "lost": 0.0, "void": 1.0,
               "half_won": None, "half_lost": 0.5}


def grade_leg(match: sqlite3.Row, market: str, selection: str,
              line: float | None, subject: str | None = None) -> str | None:
    """Grade one leg. Returns None when the result is not yet known or gradable."""
    if match is None or match["status"] != "played" or match["fthg"] is None:
        return None
    if subject:
        # Player markets need per-player match data, which no free feed provides
        # for these leagues. They are settled by hand (`vb settle-leg`).
        return None

    home, away = int(match["fthg"]), int(match["ftag"])
    total = home + away
    diff = home - away
    market, selection = market.lower(), (selection or "").lower()

    def over_under(value: float | None, threshold: float | None) -> str | None:
        if value is None or threshold is None:
            return None
        if abs(value - threshold) < 1e-9:
            return "void"
        wins_over = value > threshold
        if selection.endswith("over") or selection == "over":
            return "won" if wins_over else "lost"
        return "lost" if wins_over else "won"

    if market == "h2h":
        winner = "home" if diff > 0 else ("away" if diff < 0 else "draw")
        return "won" if selection == winner else "lost"
    if market == "double_chance":
        landed = {"1x": diff >= 0, "12": diff != 0, "x2": diff <= 0}.get(selection)
        return None if landed is None else ("won" if landed else "lost")
    if market == "dnb":
        if diff == 0:
            return "void"
        return "won" if ((diff > 0) == (selection == "home")) else "lost"
    if market == "totals":
        return over_under(total, line)
    if market == "btts":
        both = home > 0 and away > 0
        return "won" if (both == (selection == "yes")) else "lost"
    if market == "team_totals":
        side, _, _ = selection.partition("_")
        return over_under(home if side == "home" else away, line)
    if market == "ah" and line is not None:
        # `line` is the handicap on the home team, so the away side takes both
        # the mirrored margin and the mirrored line.
        if selection == "home":
            return _grade_handicap(diff, line)
        return _grade_handicap(-diff, -line)
    if market == "correct_score":
        try:
            want_home, want_away = (int(x) for x in selection.split("-"))
        except ValueError:
            return None
        return "won" if (home == want_home and away == want_away) else "lost"
    if market == "clean_sheet":
        kept = (away == 0) if selection == "home" else (home == 0)
        return "won" if kept else "lost"
    if market == "corners":
        hc, ac = match["hc"], match["ac"]
        if hc is None or ac is None:
            return None
        if selection in ("over", "under"):
            return over_under(hc + ac, line)
        side, _, _ = selection.partition("_")
        return over_under(hc if side == "home" else ac, line)
    if market == "cards":
        hy, ay = match["hy"], match["ay"]
        if hy is None or ay is None:
            return None
        reds = (match["hr"] or 0) + (match["ar"] or 0)
        if selection in ("over", "under"):
            return over_under(hy + ay + reds, line)
        side, _, _ = selection.partition("_")
        own_reds = (match["hr"] or 0) if side == "home" else (match["ar"] or 0)
        return over_under((hy if side == "home" else ay) + own_reds, line)
    if market == "booking_points":
        hy, ay = match["hy"], match["ay"]
        if hy is None or ay is None:
            return None
        points = (hy + ay) * 10 + ((match["hr"] or 0) + (match["ar"] or 0)) * 25
        return over_under(points, line)
    return None


def _grade_handicap(margin: float, line: float) -> str:
    """Grade an Asian handicap, including the quarter lines that split the stake."""
    if abs((line * 4) % 2) > 1e-9:          # .25 / .75 — half the stake on each side
        lower = _grade_handicap(margin, line - 0.25)
        upper = _grade_handicap(margin, line + 0.25)
        if lower == upper:
            return lower
        outcomes = {lower, upper}
        if outcomes == {"won", "void"}:
            return "half_won"
        if outcomes == {"lost", "void"}:
            return "half_lost"
        return "void"
    adjusted = margin + line
    if adjusted > 1e-9:
        return "won"
    if adjusted < -1e-9:
        return "lost"
    return "void"


def leg_multiplier(status: str, price: float) -> float:
    if status == "won":
        return price
    if status == "half_won":
        return 1 + (price - 1) / 2
    return MULTIPLIERS.get(status, 1.0) or 0.0


def _unbettable_books() -> list[str]:
    """Books a bet was never taken at, closing variants included.

    Closing rows are stored under the same name with "_close" appended, so both
    spellings have to be excluded.
    """
    settings = load_settings()
    names = (list(settings.get("bookmakers.exchanges", []) or [])
             + list(settings.get("bookmakers.aggregates", []) or []))
    return names + [f"{name}_close" for name in names]


def closing_price(conn: sqlite3.Connection, match_id: int, market: str,
                  selection: str, line: float | None) -> float | None:
    """The price the market finished at, for measuring closing line value.

    Drawn from the same universe the bet was taken in — real sportsbooks — and
    that restriction is the whole point. A bet is placed at the best price
    among books you can actually use; comparing it against the best price
    across *everything* at the close measures it against a benchmark it was
    never eligible to reach. "market_max" is the maximum of the panel by
    construction, so it beats every individual book's close automatically, and
    an exchange carries a fraction of a sportsbook's margin. Include either and
    closing line value is negative before a single bet is struck.
    """
    excluded = _unbettable_books()
    holes = ",".join("?" * len(excluded))
    filter_sql = f" AND o.bookmaker NOT IN ({holes})" if excluded else ""

    row = conn.execute(
        "SELECT o.price FROM odds o "
        "WHERE o.match_id = ? AND o.market = ? AND o.selection = ? "
        "AND (o.line IS ? OR o.line = ?) AND o.is_closing = 1" + filter_sql
        + " ORDER BY o.price DESC LIMIT 1",
        (match_id, market, selection, line, line, *excluded),
    ).fetchone()
    if row:
        return float(row["price"])
    row = conn.execute(
        "SELECT o.price FROM odds o JOIN matches m ON m.id = o.match_id "
        "WHERE o.match_id = ? AND o.market = ? AND o.selection = ? "
        "AND (o.line IS ? OR o.line = ?) AND o.taken_at <= m.kickoff"
        + filter_sql
        + " ORDER BY o.taken_at DESC, o.price DESC LIMIT 1",
        (match_id, market, selection, line, line, *excluded),
    ).fetchone()
    return float(row["price"]) if row else None


def settle_bets(conn: sqlite3.Connection, as_of: datetime | None = None) -> dict[str, int]:
    """Grade every pending bet whose result is in. Returns counts by outcome."""
    as_of = as_of or datetime.now()
    counts: dict[str, int] = {}
    pending = conn.execute(
        "SELECT * FROM bets WHERE status = 'pending' ORDER BY event_date"
    ).fetchall()

    for bet in pending:
        legs = conn.execute(
            "SELECT * FROM bet_legs WHERE bet_id = ? ORDER BY leg_no", (bet["id"],)
        ).fetchall()
        if not legs:
            continue

        statuses: list[str] = []
        settled_all = True
        for leg in legs:
            match = conn.execute("SELECT * FROM matches WHERE id = ?",
                                 (leg["match_id"],)).fetchone() if leg["match_id"] else None
            status = grade_leg(match, leg["market"], leg["selection"], leg["line"],
                               leg["subject"])
            if status is None:
                settled_all = False
                break
            statuses.append(status)
            conn.execute("UPDATE bet_legs SET status = ? WHERE id = ?",
                         (status, leg["id"]))
        if not settled_all:
            continue

        stake = float(bet["stake_pts"])
        if bet["bet_type"] == "acca":
            multiplier = 1.0
            for leg, status in zip(legs, statuses):
                multiplier *= leg_multiplier(status, float(leg["price"] or 1.0))
        else:
            price = float(bet["price"])
            if any(s == "lost" for s in statuses):
                multiplier = 0.0
            elif all(s == "void" for s in statuses):
                multiplier = 1.0
            elif any(s == "half_lost" for s in statuses):
                multiplier = 0.5
            elif any(s == "half_won" for s in statuses):
                multiplier = 1 + (price - 1) / 2
            else:
                multiplier = price

        returned = stake * multiplier
        pnl = returned - stake
        if multiplier == 0:
            outcome = "lost"
        elif abs(multiplier - 1.0) < 1e-9:
            outcome = "void"
        elif multiplier < 1.0:
            outcome = "half_lost"
        elif any(s == "half_won" for s in statuses):
            outcome = "half_won"
        else:
            outcome = "won"

        close = None
        clv = None
        if len(legs) == 1 and legs[0]["match_id"]:
            close = closing_price(conn, legs[0]["match_id"], legs[0]["market"],
                                  legs[0]["selection"], legs[0]["line"])
            if close and close > 1.0:
                clv = float(bet["price"]) / close - 1.0

        conn.execute(
            "UPDATE bets SET status = ?, returned_pts = ?, pnl_pts = ?, "
            "closing_price = ?, clv = ?, settled_at = ? WHERE id = ?",
            (outcome, round(returned, 4), round(pnl, 4), close, clv,
             as_of.isoformat(timespec="seconds"), bet["id"]),
        )
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


def settle_leg_manually(conn: sqlite3.Connection, ref: str, leg_no: int,
                        status: str) -> bool:
    """Grade a leg no feed can settle — a player prop, or a void selection."""
    row = conn.execute(
        "SELECT bl.id FROM bet_legs bl JOIN bets b ON b.id = bl.bet_id "
        "WHERE b.ref = ? AND bl.leg_no = ?", (ref, leg_no),
    ).fetchone()
    if not row:
        return False
    conn.execute("UPDATE bet_legs SET status = ? WHERE id = ?", (status, row["id"]))
    return True


def settle_bet_manually(conn: sqlite3.Connection, ref: str, status: str) -> bool:
    """Force a bet's result — for outrights, player props and disputed voids."""
    bet = conn.execute("SELECT * FROM bets WHERE ref = ?", (ref,)).fetchone()
    if not bet:
        return False
    stake, price = float(bet["stake_pts"]), float(bet["price"])
    multiplier = {"won": price, "lost": 0.0, "void": 1.0,
                  "half_won": 1 + (price - 1) / 2, "half_lost": 0.5}.get(status)
    if multiplier is None:
        return False
    returned = stake * multiplier
    conn.execute(
        "UPDATE bets SET status = ?, returned_pts = ?, pnl_pts = ?, settled_at = ? "
        "WHERE id = ?",
        (status, round(returned, 4), round(returned - stake, 4),
         datetime.now().isoformat(timespec="seconds"), bet["id"]),
    )
    return True
