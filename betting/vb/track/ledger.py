"""Recording tips as bets, so every recommendation is on the record.

A tipping record only means something if the losers go in as faithfully as the
winners, at the price and stake that were actually advised, at the moment they
were advised. Tips are written here the moment they are generated; nothing is
edited afterwards except the result.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from ..tips.select import Tip, TipSheet


def _leg_key(legs) -> tuple:
    """What actually identifies a bet: its legs, not the label it was given."""
    return tuple(sorted(
        (leg.get("match_id"), (leg.get("market") or "").lower(),
         (leg.get("raw_selection") or leg.get("selection") or "").lower(),
         None if leg.get("line") is None else round(float(leg["line"]), 3),
         (leg.get("subject") or "").lower())
        for leg in legs
    ))


def _tip_legs(tip: Tip) -> list[dict]:
    if tip.legs:
        return tip.legs
    if tip.match_id is not None:
        return [{"match_id": tip.match_id, "market": tip.raw_market,
                 "raw_selection": tip.raw_selection, "line": tip.raw_line,
                 "subject": tip.subject}]
    return []


def already_open(conn: sqlite3.Connection, tip: Tip) -> bool:
    """Is this same bet already on the record and unsettled?

    References carry the tip's rank within the week, so the moment a price moves
    and the ordering shifts, an identical bet arrives under a new reference.
    Deduplicating on the reference therefore let the same bet onto the ledger
    twice, which double-counts its stake and its result.
    """
    legs = _tip_legs(tip)
    if not legs:
        # Outrights have no fixture to key on.
        row = conn.execute(
            "SELECT 1 FROM bets WHERE status = 'pending' AND bet_type = ? "
            "AND selection = ? AND event_date = ?",
            (tip.kind, tip.selection, tip.event_date)).fetchone()
        return row is not None

    wanted = _leg_key(legs)
    for row in conn.execute(
            "SELECT id FROM bets WHERE status = 'pending' AND bet_type = ?",
            (tip.kind,)):
        existing = conn.execute(
            "SELECT match_id, market, selection, line, subject FROM bet_legs "
            "WHERE bet_id = ?", (row["id"],)).fetchall()
        if _leg_key([dict(leg) for leg in existing]) == wanted:
            return True
    return False


def record_tip(conn: sqlite3.Connection, tip: Tip, placed_at: str | None = None) -> int | None:
    """Write one tip to the ledger. Returns the bet id, or None if already there."""
    existing = conn.execute("SELECT id FROM bets WHERE ref = ?", (tip.ref,)).fetchone()
    if existing:
        return None
    if already_open(conn, tip):
        return None
    cur = conn.execute(
        "INSERT INTO bets (ref, placed_at, event_date, league_code, bet_type, "
        "headline, selection, market, bookmaker, price, stake_pts, model_prob, "
        "fair_prob, edge, confidence, reasoning, signals, status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'pending')",
        (
            tip.ref, placed_at or datetime.now().isoformat(timespec="seconds"),
            tip.event_date, tip.league_code, tip.kind, tip.headline, tip.selection,
            tip.market, tip.bookmaker, tip.price, tip.stake_pts, tip.model_prob,
            tip.fair_prob, tip.edge, tip.confidence, tip.body,
            json.dumps(tip.signals),
        ),
    )
    bet_id = int(cur.lastrowid)

    legs = tip.legs
    if not legs and tip.match_id is not None:
        legs = [{
            "match_id": tip.match_id,
            "market": tip.raw_market,
            "raw_selection": tip.raw_selection,
            "line": tip.raw_line,
            "price": tip.price,
            "model_prob": tip.model_prob,
            "subject": tip.subject,
        }]
    for i, leg in enumerate(legs, start=1):
        conn.execute(
            "INSERT INTO bet_legs (bet_id, leg_no, match_id, market, selection, "
            "line, subject, price, model_prob) VALUES (?,?,?,?,?,?,?,?,?)",
            (bet_id, i, leg.get("match_id"), leg.get("market", ""),
             leg.get("raw_selection", leg.get("selection", "")), leg.get("line"),
             leg.get("subject"), leg.get("price"), leg.get("model_prob")),
        )
    return bet_id


def record_tipsheet(conn: sqlite3.Connection, sheet: TipSheet) -> dict[str, int]:
    """Write a whole week's tips. Returns counts by kind."""
    counts: dict[str, int] = {}
    for tip in sheet.all_tips:
        if record_tip(conn, tip, placed_at=sheet.generated_at) is not None:
            counts[tip.kind] = counts.get(tip.kind, 0) + 1
    return counts


def open_bets(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM bets WHERE status = 'pending' ORDER BY event_date"
    ).fetchall()


def all_bets(conn: sqlite3.Connection, season_start: str | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM bets"
    params: list = []
    if season_start:
        sql += " WHERE event_date >= ?"
        params.append(season_start)
    return conn.execute(sql + " ORDER BY event_date, id", params).fetchall()


def legs_for(conn: sqlite3.Connection, bet_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM bet_legs WHERE bet_id = ? ORDER BY leg_no", (bet_id,)
    ).fetchall()


def set_price_taken(conn: sqlite3.Connection, ref: str, price: float,
                    stake: float | None = None) -> bool:
    """Record the price you actually got — builders especially never match the quote."""
    row = conn.execute("SELECT id FROM bets WHERE ref = ?", (ref,)).fetchone()
    if not row:
        return False
    if stake is None:
        conn.execute("UPDATE bets SET price = ? WHERE id = ?", (price, row["id"]))
    else:
        conn.execute("UPDATE bets SET price = ?, stake_pts = ? WHERE id = ?",
                     (price, stake, row["id"]))
    return True


def void_bet(conn: sqlite3.Connection, ref: str, note: str = "") -> bool:
    row = conn.execute("SELECT id, stake_pts FROM bets WHERE ref = ?", (ref,)).fetchone()
    if not row:
        return False
    conn.execute(
        "UPDATE bets SET status = 'void', returned_pts = stake_pts, pnl_pts = 0, "
        "settled_at = ?, notes = ? WHERE id = ?",
        (datetime.now().isoformat(timespec="seconds"), note, row["id"]),
    )
    return True


def mark_placed(conn: sqlite3.Connection, ref: str, price: float | None = None,
                stake: float | None = None) -> bool:
    """Record that a tip was actually backed, and at what.

    Advice and action are tracked separately: the tipping record stands whether
    or not you struck the bet, and your own record only counts the ones you did.
    Prices move, so the price taken is rarely the price advised.
    """
    row = conn.execute("SELECT id, price, stake_pts FROM bets WHERE ref = ?",
                       (ref,)).fetchone()
    if not row:
        return False
    conn.execute(
        "UPDATE bets SET placed = 1, placed_price = ?, placed_stake = ? WHERE id = ?",
        (price if price is not None else row["price"],
         stake if stake is not None else row["stake_pts"], row["id"]),
    )
    return True


def mark_passed(conn: sqlite3.Connection, ref: str) -> bool:
    """Record that a tip was advised but deliberately not backed."""
    row = conn.execute("SELECT id FROM bets WHERE ref = ?", (ref,)).fetchone()
    if not row:
        return False
    conn.execute(
        "UPDATE bets SET placed = 0, placed_price = NULL, placed_stake = NULL "
        "WHERE id = ?", (row["id"],))
    return True


def find_duplicates(conn: sqlite3.Connection) -> list[dict]:
    """Unsettled bets recorded more than once under different references."""
    seen: dict[tuple, list[str]] = {}
    for row in conn.execute(
            "SELECT id, ref, selection FROM bets WHERE status = 'pending'"):
        legs = conn.execute(
            "SELECT match_id, market, selection, line, subject FROM bet_legs "
            "WHERE bet_id = ?", (row["id"],)).fetchall()
        if not legs:
            continue
        seen.setdefault(_leg_key([dict(leg) for leg in legs]),
                        []).append((row["ref"], row["selection"]))
    return [{"refs": [r for r, _ in group], "selection": group[0][1]}
            for group in seen.values() if len(group) > 1]


def drop_open_bets(conn: sqlite3.Connection, before: str | None = None,
                   refs: list[str] | None = None) -> int:
    """Remove unsettled bets from the record.

    For clearing advice produced by a version of the engine since found to be
    wrong. Settled bets are never touched: a record you can delete losers from
    is not a record.
    """
    if refs:
        placeholders = ",".join("?" * len(refs))
        cur = conn.execute(
            f"DELETE FROM bets WHERE status = 'pending' AND ref IN ({placeholders})",
            refs)
    elif before:
        cur = conn.execute(
            "DELETE FROM bets WHERE status = 'pending' AND placed_at < ?", (before,))
    else:
        cur = conn.execute("DELETE FROM bets WHERE status = 'pending'")
    return cur.rowcount or 0
