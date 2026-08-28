"""Rendering the ledger as a single self-contained HTML page.

The page has one job: show whether the tipping is working, and let you read
back any individual bet to see why it was advised. Summary first, detail
underneath — and the diagnostics that matter (closing line value, calibration,
expected versus actual) given the same prominence as the profit figure, because
over a small number of bets they are more informative than it is.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import REPORT_DIR, ensure_dirs, load_leagues, load_settings
from ..tips.select import TipSheet
from ..track import metrics

TEMPLATE_DIR = Path(__file__).parent / "templates"

STATUS_LABELS = {
    "won": "Won", "lost": "Lost", "void": "Void",
    "half_won": "Won ½", "half_lost": "Lost ½", "pending": "Open",
}


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True, lstrip_blocks=True,
    )
    env.filters["pts"] = _format_points
    env.filters["signed_pct"] = lambda v: f"{v:+.1%}" if v is not None else "—"
    env.filters["pct"] = lambda v: f"{v:.1%}" if v is not None else "—"
    env.filters["odds"] = lambda v: f"{v:.2f}" if v else "—"
    return env


def _format_points(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}" if value else "0.00"


def ledger_rows(conn: sqlite3.Connection, season_start: str | None = None,
                limit: int | None = None) -> list[dict]:
    """Every bet, newest first, with the running points total attached."""
    rows = conn.execute(
        "SELECT * FROM bets" + (" WHERE event_date >= ?" if season_start else "")
        + " ORDER BY event_date, id",
        ([season_start] if season_start else []),
    ).fetchall()
    leagues = load_leagues()
    running = 0.0
    out: list[dict] = []
    for row in rows:
        pnl = float(row["pnl_pts"]) if row["pnl_pts"] is not None else None
        if pnl is not None:
            running += pnl
        league = leagues.get(row["league_code"])
        out.append({
            "ref": row["ref"],
            "date": row["event_date"],
            "league": league.name if league else (row["league_code"] or "—"),
            "league_code": row["league_code"] or "",
            "type": row["bet_type"],
            "selection": row["selection"],
            "market": row["market"] or "",
            "book": row["bookmaker"] or "",
            "price": float(row["price"] or 0),
            "stake": float(row["stake_pts"] or 0),
            "status": row["status"],
            "status_label": STATUS_LABELS.get(row["status"], row["status"]),
            "pnl": pnl,
            "running": round(running, 2) if pnl is not None else None,
            "edge": float(row["edge"] or 0),
            "confidence": int(row["confidence"] or 0),
            "reasoning": row["reasoning"] or "",
            "clv": float(row["clv"]) if row["clv"] is not None else None,
        })
    out.reverse()
    return out[:limit] if limit else out


def build_context(
    conn: sqlite3.Connection,
    sheet: TipSheet | None = None,
    season_start: str | None = None,
    synthetic: bool = False,
) -> dict:
    settings = load_settings()
    summary = metrics.summarise(conn, season_start)
    curve = metrics.running_pnl(conn, season_start)
    rows = ledger_rows(conn, season_start)

    tips = []
    if sheet:
        for tip in sheet.all_tips:
            tips.append({
                "ref": tip.ref, "kind": tip.kind, "headline": tip.headline,
                "body": tip.body, "selection": tip.selection, "market": tip.market,
                "league": (load_leagues().get(tip.league_code).name
                           if load_leagues().get(tip.league_code) else tip.league_code),
                "date": tip.event_date, "price": tip.price, "stake": tip.stake_pts,
                "edge": tip.edge, "confidence": tip.confidence, "stars": tip.stars,
                "book": tip.bookmaker, "fixture": tip.fixture,
                "signals": tip.signals, "legs": tip.legs,
                "target_price": tip.target_price,
                "is_botw": bool(sheet.bet_of_the_week
                                and tip.ref == sheet.bet_of_the_week.ref),
            })

    return {
        "title": settings.get("report.title", "The Value Ledger"),
        "season": settings.get("report.season", ""),
        "tipster": settings.get("report.tipster_name", ""),
        "generated": datetime.now().strftime("%d %B %Y, %H:%M"),
        "synthetic": synthetic,
        "summary": summary,
        "curve": curve,
        "curve_json": json.dumps([{"d": d, "p": p} for d, p, _ in curve]),
        "bets": rows,
        "open_bets": [r for r in rows if r["status"] == "pending"],
        "tips": tips,
        "bet_of_week": next((t for t in tips if t["is_botw"]), None),
        "by_league": _name_leagues(metrics.by_league(conn, season_start)),
        "by_market": metrics.by_market(conn, season_start),
        "by_type": metrics.by_type(conn, season_start),
        "by_month": metrics.by_month(conn, season_start),
        "calibration": metrics.calibration(conn, season_start),
        "sheet": sheet,
    }


def _name_leagues(rows: list[dict]) -> list[dict]:
    """Swap league codes for their proper names in the breakdown."""
    leagues = load_leagues()
    for row in rows:
        league = leagues.get(row["name"])
        if league:
            row["name"] = league.name
    return rows


def render(context: dict) -> str:
    return _environment().get_template("dashboard.html.j2").render(**context)


def write(
    conn: sqlite3.Connection,
    path: str | Path | None = None,
    sheet: TipSheet | None = None,
    season_start: str | None = None,
    synthetic: bool = False,
) -> Path:
    ensure_dirs()
    target = Path(path) if path else REPORT_DIR / "dashboard.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(build_context(conn, sheet, season_start, synthetic)),
                      encoding="utf-8")
    return target
