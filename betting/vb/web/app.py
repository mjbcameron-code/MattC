"""A small local web app, so the ledger can be used rather than only read.

The HTML dashboard is a report: it tells you what happened. This adds the parts
a file cannot do — running a refresh, marking which advice you actually acted
on and at what price, and settling without going near a terminal.

It listens on localhost only. There is no authentication because there is
nothing to authenticate: it serves one person's betting record on their own
machine, and binding it anywhere else would be a mistake rather than a feature.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from flask import Flask, jsonify, redirect, render_template, request, url_for

from ..config import load_leagues, load_settings
from ..db import session
from ..report.dashboard import ledger_rows
from ..tips.select import build_tipsheet
from ..track import metrics
from ..track.ledger import mark_passed, mark_placed, record_tipsheet
from ..track.settle import settle_bets

app = Flask(__name__)
app.config["DB_PATH"] = None


class Job:
    """One background task at a time, with its progress readable from the page.

    Refreshing three seasons across fourteen leagues takes minutes. Doing it in
    the request would hang the browser and tell the user nothing, so it runs on
    a thread and the page polls for the log.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.name: str | None = None
        self.lines: list[str] = []
        self.finished = True
        self.started: datetime | None = None

    def start(self, name: str, target) -> bool:
        with self.lock:
            if not self.finished:
                return False
            self.name, self.lines, self.finished = name, [], False
            self.started = datetime.now()

        def run() -> None:
            try:
                target(self.log)
            except Exception as exc:                    # noqa: BLE001
                self.log(f"stopped: {exc}")
            finally:
                self.finished = True

        threading.Thread(target=run, daemon=True).start()
        return True

    def log(self, line: str) -> None:
        self.lines.append(str(line))

    def state(self) -> dict[str, Any]:
        return {"name": self.name, "lines": self.lines[-40:],
                "running": not self.finished}


job = Job()


def db():
    return session(app.config["DB_PATH"])


# ---------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------
@app.route("/")
def home():
    settings = load_settings()
    leagues = load_leagues()
    with db() as conn:
        summary = metrics.summarise(conn)
        bets = ledger_rows(conn, limit=200)
        open_tips = [b for b in bets if b["status"] == "pending"]
        placed = conn.execute(
            "SELECT ref, placed, placed_price, placed_stake FROM bets").fetchall()
        placed_by_ref = {r["ref"]: dict(r) for r in placed}
        curve = metrics.running_pnl(conn)
        by_league = metrics.by_league(conn)
        for row in by_league:
            league = leagues.get(row["name"])
            if league:
                row["name"] = league.name
        counts = conn.execute(
            "SELECT COUNT(*) AS matches, "
            "SUM(status = 'scheduled') AS ahead FROM matches").fetchone()
        placed_summary = _placed_summary(conn)
    return render_template(
        "app.html",
        title=settings.get("report.title", "The Value Ledger"),
        season=settings.get("report.season", ""),
        summary=summary, placed=placed_summary, bets=bets, open_tips=open_tips,
        placed_by_ref=placed_by_ref, curve=curve, by_league=by_league,
        matches=counts["matches"] or 0, ahead=counts["ahead"] or 0,
        generated=datetime.now().strftime("%d %B %Y, %H:%M"),
    )


def _placed_summary(conn) -> dict[str, float]:
    """Your record, as opposed to the tipping record."""
    row = conn.execute(
        "SELECT COUNT(*) AS n, "
        "COALESCE(SUM(placed_stake), 0) AS staked, "
        "COALESCE(SUM(CASE WHEN status IN ('won','half_won') "
        "  THEN placed_stake * (placed_price - 1) "
        "  WHEN status = 'lost' THEN -placed_stake "
        "  WHEN status = 'half_lost' THEN -placed_stake / 2 "
        "  ELSE 0 END), 0) AS pnl, "
        "SUM(status = 'pending') AS pending "
        "FROM bets WHERE placed = 1").fetchone()
    staked = float(row["staked"] or 0)
    pnl = float(row["pnl"] or 0)
    return {"bets": row["n"] or 0, "staked": staked, "pnl": pnl,
            "pending": row["pending"] or 0,
            "roi": (pnl / staked) if staked else 0.0}


# ---------------------------------------------------------------------------
# actions
# ---------------------------------------------------------------------------
@app.post("/act/refresh")
def act_refresh():
    def work(log):
        from ..features.suspensions import derive_suspensions
        from ..sources import footballdata

        season = load_settings().get("report.season", "2026/27")
        codes = [lg.code for lg in load_leagues().values() if lg.enabled]
        with db() as conn:
            log("Fetching this week's fixtures and prices…")
            try:
                counts = footballdata.load_fixtures(conn, season, codes)
                log(f"  {sum(counts.values())} fixtures in")
            except Exception as exc:                    # noqa: BLE001
                log(f"  fixtures unavailable: {exc}")
            written = derive_suspensions(conn)
            if written:
                log(f"  {written} suspension(s) from recent red cards")
            log("Settling anything finished…")
            outcome = settle_bets(conn)
            log(f"  {sum(outcome.values()) or 'nothing'} settled")
        log("Done.")

    job.start("Refreshing", work)
    return redirect(url_for("home"))


@app.post("/act/card")
def act_card():
    def work(log):
        with db() as conn:
            log("Pricing this week's fixtures…")
            sheet = build_tipsheet(conn, days=7)
            log(f"  {sheet.fixtures_scanned} fixtures, "
                f"{len(sheet.all_tips)} bets advised")
            written = record_tipsheet(conn, sheet)
            log(f"  {sum(written.values())} new tip(s) on the record")
        log("Done — reload to see the card.")

    job.start("Building the card", work)
    return redirect(url_for("home"))


@app.post("/bet/<ref>/placed")
def bet_placed(ref: str):
    price = request.form.get("price", type=float)
    stake = request.form.get("stake", type=float)
    with db() as conn:
        mark_placed(conn, ref, price, stake)
    return redirect(url_for("home") + "#card")


@app.post("/bet/<ref>/passed")
def bet_passed(ref: str):
    with db() as conn:
        mark_passed(conn, ref)
    return redirect(url_for("home") + "#card")


@app.get("/job")
def job_state():
    return jsonify(job.state())


def serve(db_path=None, port: int = 5137, open_browser: bool = True) -> None:
    app.config["DB_PATH"] = str(db_path) if db_path else None
    url = f"http://127.0.0.1:{port}/"
    if open_browser:
        threading.Timer(1.0, lambda: __import__("webbrowser").open(url)).start()
    print(f"\n  The Value Ledger is running at {url}")
    print("  Leave this window open while you use it. Press Control-C to stop.\n")
    app.run(host="127.0.0.1", port=port, debug=False)
