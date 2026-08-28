"""Walk-forward backtesting: what would this system have advised, and how did it do?

The point of a backtest here is not to produce a flattering number. It is to
answer two questions honestly:

* would the selection rules have picked bets at all, week after week?
* did the edge the model claimed actually turn into points?

The run is strictly walk-forward. At each week the models are refitted using
only matches played before that date, prices are read as they stood at the
time, and the bets are then settled against what actually happened. Nothing
from the future leaks backwards — which is the one mistake that makes every
betting backtest look brilliant.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .config import load_settings
from .tips.select import build_tipsheet
from .track import metrics
from .track.ledger import record_tipsheet
from .track.settle import settle_bets


@dataclass
class BacktestResult:
    weeks: int = 0
    tips: int = 0
    summary: metrics.Summary = field(default_factory=metrics.Summary)
    by_market: list[dict] = field(default_factory=list)
    by_league: list[dict] = field(default_factory=list)
    calibration: list[dict] = field(default_factory=list)
    curve: list[tuple[str, float, float]] = field(default_factory=list)
    first_date: str = ""
    last_date: str = ""


def season_window(conn: sqlite3.Connection, season: str | None = None
                  ) -> tuple[datetime, datetime] | None:
    sql = "SELECT MIN(kickoff) AS first, MAX(kickoff) AS last FROM matches WHERE status = 'played'"
    params: list = []
    if season:
        sql += " AND season = ?"
        params.append(season)
    row = conn.execute(sql, params).fetchone()
    if not row or not row["first"]:
        return None
    return (datetime.fromisoformat(row["first"][:19]),
            datetime.fromisoformat(row["last"][:19]))


def run(
    conn: sqlite3.Connection,
    season: str | None = None,
    leagues: list[str] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    warmup_weeks: int = 8,
    step_days: int = 7,
    include_outrights: bool = False,
    progress=None,
) -> BacktestResult:
    """Replay the season a week at a time, tipping and settling as it goes."""
    window = season_window(conn, season)
    if window is None:
        return BacktestResult()
    first, last = window
    cursor = start or (first + timedelta(weeks=warmup_weeks))
    finish = end or last
    settings = load_settings()
    season = season or settings.get("report.season", "2025/26")

    result = BacktestResult(first_date=cursor.date().isoformat(),
                            last_date=finish.date().isoformat())
    week = 0
    while cursor <= finish:
        sheet = build_tipsheet(
            conn, days=step_days, leagues=leagues, as_of=cursor, season=season,
            include_outrights=include_outrights, statuses=("played", "scheduled"),
        )
        # Refs must be unique across the whole run, not just within a week.
        for tip in sheet.all_tips:
            tip.ref = f"BT{week:03d}-{tip.ref}"
        recorded = record_tipsheet(conn, sheet)
        result.tips += sum(recorded.values())
        settle_bets(conn, as_of=cursor + timedelta(days=step_days + 1))
        if progress:
            progress(cursor, sum(recorded.values()), result.tips)
        cursor += timedelta(days=step_days)
        week += 1

    settle_bets(conn, as_of=finish + timedelta(days=7))
    result.weeks = week
    result.summary = metrics.summarise(conn)
    result.by_market = metrics.by_market(conn)
    result.by_league = metrics.by_league(conn)
    result.calibration = metrics.calibration(conn)
    result.curve = metrics.running_pnl(conn)
    return result
