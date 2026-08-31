"""Season figures: points, ROI, strike rate, closing line value, drawdown.

Points are the headline because that is how a tipping record is read, but the
two numbers that actually tell you whether the model works are closing line
value (are we taking better prices than the market settles on?) and expected
versus actual profit (is the edge the model claims showing up?). Both are here.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

SETTLED = ("won", "lost", "void", "half_won", "half_lost")
WINNING = ("won", "half_won")


@dataclass
class Summary:
    bets: int = 0
    settled: int = 0
    pending: int = 0
    staked: float = 0.0
    returned: float = 0.0
    pnl: float = 0.0
    won: int = 0
    lost: int = 0
    void: int = 0
    average_odds: float = 0.0
    average_stake: float = 0.0
    average_edge: float = 0.0
    expected_pnl: float = 0.0
    #: One standard error on the ROI. Without it a headline ROI over a
    #: couple of hundred bets invites a conclusion the sample cannot
    #: support: at these prices the noise is wider than any edge a
    #: model of this kind could plausibly have.
    roi_stderr: float = 0.0
    clv_measured: int = 0
    clv_average: float = 0.0
    clv_beat_rate: float = 0.0
    best_run: int = 0
    worst_run: int = 0
    max_drawdown: float = 0.0
    peak: float = 0.0

    @property
    def roi(self) -> float:
        return self.pnl / self.staked if self.staked else 0.0

    @property
    def strike_rate(self) -> float:
        decided = self.won + self.lost
        return self.won / decided if decided else 0.0

    @property
    def yield_per_bet(self) -> float:
        return self.pnl / self.settled if self.settled else 0.0


def _rows(conn: sqlite3.Connection, season_start: str | None,
          priced_only: bool = False) -> list[sqlite3.Row]:
    sql = "SELECT * FROM bets"
    where: list[str] = []
    params: list = []
    if season_start:
        where.append("event_date >= ?")
        params.append(season_start)
    if priced_only:
        # Bets advised at a price no bookmaker was seen to offer. A bet builder
        # is quoted as a target — "take it at 6.98 or bigger" — computed from
        # our own fair price, and settled at that number. Its profit and loss is
        # therefore a restatement of the model, not a measurement of it: raise
        # the price we demand and the figures improve without a single bet
        # changing. An accumulator is different, and stays in: its price is the
        # product of real quotes, which is what a book actually pays.
        where.append("bookmaker IS NOT NULL AND bookmaker != ''")
    if where:
        sql += " WHERE " + " AND ".join(where)
    return conn.execute(sql + " ORDER BY event_date, id", params).fetchall()


def summarise(conn: sqlite3.Connection, season_start: str | None = None,
              priced_only: bool = False) -> Summary:
    rows = _rows(conn, season_start, priced_only)
    summary = Summary(bets=len(rows))
    odds_total = stake_total = edge_total = 0.0
    clv_values: list[float] = []
    pnls: list[float] = []
    running = 0.0
    peak = 0.0
    streak = 0
    for row in rows:
        if row["status"] == "pending":
            summary.pending += 1
            continue
        summary.settled += 1
        stake = float(row["stake_pts"] or 0)
        summary.staked += stake
        summary.returned += float(row["returned_pts"] or 0)
        summary.pnl += float(row["pnl_pts"] or 0)
        odds_total += float(row["price"] or 0) * stake
        stake_total += stake
        edge_total += float(row["edge"] or 0) * stake
        summary.expected_pnl += stake * (
            float(row["model_prob"] or 0) * float(row["price"] or 0) - 1
        )
        if row["status"] in WINNING:
            summary.won += 1
            streak = streak + 1 if streak >= 0 else 1
        elif row["status"] == "void":
            summary.void += 1
        else:
            summary.lost += 1
            streak = streak - 1 if streak <= 0 else -1
        summary.best_run = max(summary.best_run, streak)
        summary.worst_run = min(summary.worst_run, streak)
        pnls.append(float(row["pnl_pts"] or 0))
        if row["clv"] is not None:
            clv_values.append(float(row["clv"]))

        running += float(row["pnl_pts"] or 0)
        peak = max(peak, running)
        summary.max_drawdown = max(summary.max_drawdown, peak - running)

    summary.peak = peak
    if stake_total:
        summary.average_odds = odds_total / stake_total
        summary.average_edge = edge_total / stake_total
        summary.average_stake = stake_total / summary.settled if summary.settled else 0.0
    if len(pnls) > 1 and summary.staked:
        mean = sum(pnls) / len(pnls)
        variance = sum((v - mean) ** 2 for v in pnls) / (len(pnls) - 1)
        summary.roi_stderr = (variance ** 0.5) * (len(pnls) ** 0.5) / summary.staked
    if clv_values:
        summary.clv_measured = len(clv_values)
        summary.clv_average = sum(clv_values) / len(clv_values)
        summary.clv_beat_rate = sum(1 for v in clv_values if v > 0) / len(clv_values)
    return summary


def running_pnl(conn: sqlite3.Connection, season_start: str | None = None
                ) -> list[tuple[str, float, float]]:
    """(date, cumulative points, cumulative staked) after each settled bet."""
    rows = [r for r in _rows(conn, season_start) if r["status"] in SETTLED]
    out: list[tuple[str, float, float]] = []
    total = staked = 0.0
    for row in rows:
        total += float(row["pnl_pts"] or 0)
        staked += float(row["stake_pts"] or 0)
        out.append((row["event_date"], round(total, 2), round(staked, 2)))
    return out


def _group(conn: sqlite3.Connection, key: str, season_start: str | None
           ) -> list[dict]:
    rows = [r for r in _rows(conn, season_start) if r["status"] in SETTLED]
    buckets: dict[str, dict] = defaultdict(
        lambda: {"bets": 0, "staked": 0.0, "pnl": 0.0, "won": 0, "lost": 0}
    )
    for row in rows:
        bucket = buckets[str(row[key] or "—")]
        bucket["bets"] += 1
        bucket["staked"] += float(row["stake_pts"] or 0)
        bucket["pnl"] += float(row["pnl_pts"] or 0)
        if row["status"] in WINNING:
            bucket["won"] += 1
        elif row["status"] != "void":
            bucket["lost"] += 1
    out = []
    for name, bucket in buckets.items():
        out.append({
            "name": name, **bucket,
            "roi": bucket["pnl"] / bucket["staked"] if bucket["staked"] else 0.0,
            "strike": bucket["won"] / (bucket["won"] + bucket["lost"])
                      if (bucket["won"] + bucket["lost"]) else 0.0,
        })
    return sorted(out, key=lambda b: -b["pnl"])


def by_market(conn, season_start=None):
    return _group(conn, "market", season_start)


def by_league(conn, season_start=None):
    return _group(conn, "league_code", season_start)


def by_type(conn, season_start=None):
    return _group(conn, "bet_type", season_start)


def by_confidence(conn, season_start=None):
    return sorted(_group(conn, "confidence", season_start),
                  key=lambda b: b["name"], reverse=True)


def by_month(conn: sqlite3.Connection, season_start: str | None = None) -> list[dict]:
    rows = [r for r in _rows(conn, season_start) if r["status"] in SETTLED]
    buckets: dict[str, dict] = defaultdict(
        lambda: {"bets": 0, "staked": 0.0, "pnl": 0.0, "won": 0, "lost": 0})
    for row in rows:
        bucket = buckets[(row["event_date"] or "")[:7]]
        bucket["bets"] += 1
        bucket["staked"] += float(row["stake_pts"] or 0)
        bucket["pnl"] += float(row["pnl_pts"] or 0)
        if row["status"] in WINNING:
            bucket["won"] += 1
        elif row["status"] != "void":
            bucket["lost"] += 1
    return [
        {"name": name, **bucket,
         "roi": bucket["pnl"] / bucket["staked"] if bucket["staked"] else 0.0}
        for name, bucket in sorted(buckets.items())
    ]


def calibration(conn: sqlite3.Connection, season_start: str | None = None,
                buckets: int = 5) -> list[dict]:
    """Did things the model called 60% actually happen 60% of the time?

    The single most useful diagnostic there is: a model that is well calibrated
    but unprofitable needs better prices, while one that is miscalibrated needs
    fixing before another bet is placed.
    """
    rows = [r for r in _rows(conn, season_start)
            if r["status"] in SETTLED and r["status"] != "void"
            and r["model_prob"] is not None]
    if not rows:
        return []
    edges = [i / buckets for i in range(buckets + 1)]
    out = []
    for low, high in zip(edges, edges[1:]):
        chunk = [r for r in rows if low <= float(r["model_prob"]) < high
                 or (high == 1.0 and float(r["model_prob"]) == 1.0)]
        if not chunk:
            continue
        wins = sum(1 for r in chunk if r["status"] in WINNING)
        out.append({
            "range": f"{low:.0%}–{high:.0%}",
            "bets": len(chunk),
            "predicted": sum(float(r["model_prob"]) for r in chunk) / len(chunk),
            "actual": wins / len(chunk),
        })
    return out
