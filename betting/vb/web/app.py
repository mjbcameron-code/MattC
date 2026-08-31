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
        coverage, coverage_built, coverage_stale = _coverage(conn, leagues)
    # Name the correction the card was built under. It reshapes every edge on
    # the page, and a thin card with no explanation on it reads as a fault.
    slope = float(settings.get("model.calibration.slope", 1.0))
    intercept = float(settings.get("model.calibration.intercept", 0.0))
    calibration = None if (slope, intercept) == (1.0, 0.0) else {
        "slope": slope, "intercept": intercept}
    return render_template(
        "app.html",
        title=settings.get("report.title", "The Value Ledger"),
        season=settings.get("report.season", ""),
        summary=summary, placed=placed_summary, bets=bets, open_tips=open_tips,
        placed_by_ref=placed_by_ref, curve=curve, by_league=by_league,
        matches=counts["matches"] or 0, ahead=counts["ahead"] or 0,
        coverage=coverage, coverage_built=coverage_built,
        calibration=calibration,
        coverage_stale=coverage_stale,
        generated=datetime.now().strftime("%d %B %Y, %H:%M"),
    )


def _coverage(conn, leagues) -> tuple[list[dict[str, Any]], str, bool]:
    """What the engine saw last time it priced up, and what stopped each price.

    Silence from a division reads the same on the card whether the prices were
    judged fair or never arrived. This is the difference, per league.
    """
    from ..db import get_setting
    from ..market.value import Trace

    trace = Trace.from_json(get_setting(conn, "coverage.trace"))
    built = get_setting(conn, "coverage.built_at") or ""
    if built:
        try:
            built = datetime.fromisoformat(built).strftime("%d %B, %H:%M")
        except ValueError:
            pass
    out = []
    for code in trace.leagues():
        rows = trace.rows(code)
        counts = dict(rows)
        out.append({
            "name": leagues[code].name if code in leagues else code,
            "considered": trace.total(code),
            "tipped": counts.get("tipped", 0),
            "reasons": [{"reason": r, "count": n} for r, n in rows
                        if r != "tipped"],
            "weight": trace.weight(code),
            "best": [{"edge": e, "label": lbl}
                     for e, lbl in trace.near_misses(code)],
        })
    out.sort(key=lambda r: (-r["tipped"], -r["considered"]))
    # Rendering a record from an older build silently looks exactly like a
    # fresh run that found nothing to say, so it has to announce itself. The
    # format it was written in is the only reliable test: a record can carry
    # every field this reader wants and still hold an older shape in them.
    stale = bool(out) and trace.format < Trace.FORMAT
    return out, built, stale


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
        from ..db import set_setting
        from ..market.value import Trace

        with db() as conn:
            log("Pricing this week's fixtures…")
            trace = Trace()
            sheet = build_tipsheet(conn, days=7, trace=trace)
            log(f"  {sheet.fixtures_scanned} fixtures, "
                f"{len(sheet.all_tips)} bets advised")
            # Keep the account of what was seen and why it was passed over, so
            # the Health tab can answer "why is there nothing from X?" without
            # a second, expensive pricing run.
            set_setting(conn, "coverage.trace", trace.to_json())
            set_setting(conn, "coverage.built_at", datetime.now().isoformat())
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
