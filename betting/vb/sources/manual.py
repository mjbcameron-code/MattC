"""CSV import/export — the no-API-key path, and the only route for team news.

Three things have no free structured feed worth trusting:

* prices for the Scottish lower leagues and the National League,
* injury and suspension news,
* player minutes/shots/cards outside the big leagues.

All three are handled with small CSVs you can fill in by hand in a couple of
minutes a week. `vb template <kind>` writes a pre-populated file with this
weekend's fixtures already in it, so you only type the numbers.
"""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from ..config import DATA_DIR
from ..repo import find_match, resolve_team, upsert_match, upsert_odds

ODDS_HEADER = ["date", "league", "home", "away", "market", "selection", "line",
               "bookmaker", "price"]
RESULTS_HEADER = ["date", "league", "home", "away", "fthg", "ftag", "hs", "as",
                  "hst", "ast", "hc", "ac", "hy", "ay", "hr", "ar", "referee"]
NEWS_HEADER = ["date", "league", "team", "player", "kind", "detail", "impact"]
PLAYER_HEADER = ["player", "team", "league", "season", "position", "apps",
                 "minutes", "goals", "shots", "sot", "fouls", "yellows", "reds"]


def _upcoming(conn: sqlite3.Connection, days: int, leagues: list[str] | None):
    today = datetime.now().date()
    end = today + timedelta(days=days)
    sql = (
        "SELECT m.id, m.league_code, m.match_date, h.name AS home, a.name AS away "
        "FROM matches m JOIN teams h ON h.id = m.home_id JOIN teams a ON a.id = m.away_id "
        "WHERE m.status = 'scheduled' AND m.match_date BETWEEN ? AND ?"
    )
    params: list = [today.isoformat(), end.isoformat()]
    if leagues:
        sql += f" AND m.league_code IN ({','.join('?' * len(leagues))})"
        params += leagues
    return conn.execute(sql + " ORDER BY m.match_date, m.league_code", params).fetchall()


def odds_template(conn: sqlite3.Connection, path: str | Path | None = None,
                  days: int = 8, leagues: list[str] | None = None,
                  bookmaker: str = "skybet") -> Path:
    """Write a CSV with this week's fixtures and blank price cells."""
    path = Path(path or DATA_DIR / "odds_input.csv")
    rows = []
    for match in _upcoming(conn, days, leagues):
        base = [match["match_date"], match["league_code"], match["home"], match["away"]]
        for market, selection, line in (
            ("h2h", "home", ""), ("h2h", "draw", ""), ("h2h", "away", ""),
            ("totals", "over", 2.5), ("totals", "under", 2.5),
            ("btts", "yes", ""), ("btts", "no", ""),
            ("corners", "over", 9.5), ("corners", "under", 9.5),
        ):
            rows.append([*base, market, selection, line, bookmaker, ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(ODDS_HEADER)
        writer.writerows(rows)
    return path


def load_odds(conn: sqlite3.Connection, path: str | Path, season: str) -> int:
    """Read hand-entered prices back in. Blank price cells are skipped."""
    loaded = 0
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            price = (row.get("price") or "").strip()
            if not price:
                continue
            match = find_match(conn, row["league"], row["home"], row["away"], row["date"])
            if match is None:
                match_id = upsert_match(
                    conn, row["league"], season, f"{row['date']}T15:00:00",
                    row["home"], row["away"], source="manual",
                )
            else:
                match_id = match["id"]
            line = (row.get("line") or "").strip()
            upsert_odds(
                conn, match_id, row.get("bookmaker") or "manual", row["market"],
                row["selection"], float(price),
                float(line) if line else None,
                taken_at=datetime.now().isoformat(timespec="seconds"),
            )
            loaded += 1
    return loaded


def results_template(conn: sqlite3.Connection, path: str | Path | None = None,
                     days: int = 8, leagues: list[str] | None = None) -> Path:
    path = Path(path or DATA_DIR / "results_input.csv")
    today = datetime.now().date()
    start = today - timedelta(days=days)
    sql = (
        "SELECT m.league_code, m.match_date, h.name AS home, a.name AS away "
        "FROM matches m JOIN teams h ON h.id = m.home_id JOIN teams a ON a.id = m.away_id "
        "WHERE m.status = 'scheduled' AND m.match_date BETWEEN ? AND ?"
    )
    params: list = [start.isoformat(), today.isoformat()]
    if leagues:
        sql += f" AND m.league_code IN ({','.join('?' * len(leagues))})"
        params += leagues
    rows = conn.execute(sql + " ORDER BY m.match_date", params).fetchall()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(RESULTS_HEADER)
        for r in rows:
            writer.writerow([r["match_date"], r["league_code"], r["home"], r["away"]]
                            + [""] * (len(RESULTS_HEADER) - 4))
    return path


def load_results(conn: sqlite3.Connection, path: str | Path, season: str) -> int:
    loaded = 0
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            if not (row.get("fthg") or "").strip():
                continue
            stats = {"source": "manual"}
            for key in ("fthg", "ftag", "hs", "as", "hst", "ast", "hc", "ac",
                        "hy", "ay", "hr", "ar"):
                value = (row.get(key) or "").strip()
                if value:
                    stats[key] = int(float(value))
            if (row.get("referee") or "").strip():
                stats["referee"] = row["referee"].strip()
            upsert_match(
                conn, row["league"], season, f"{row['date']}T15:00:00",
                row["home"], row["away"], status="played", **stats,
            )
            loaded += 1
    return loaded


def news_template(conn: sqlite3.Connection, path: str | Path | None = None,
                  days: int = 8, leagues: list[str] | None = None) -> Path:
    """One row per team with a fixture coming up, ready for you to fill in."""
    path = Path(path or DATA_DIR / "team_news.csv")
    existing: set[tuple] = set()
    if Path(path).exists():
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                existing.add((row.get("date"), row.get("team"), row.get("player")))
    rows = []
    for match in _upcoming(conn, days, leagues):
        for side in ("home", "away"):
            rows.append([match["match_date"], match["league_code"], match[side],
                         "", "", "", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(NEWS_HEADER)
        writer.writerows(rows)
    return path


IMPACT_DEFAULTS = {
    "injury": 0.10,
    "suspension": 0.10,
    "doubt": 0.05,
    "return": -0.08,      # negative impact = the team gets stronger
    "rested": 0.06,
}


def load_team_news(conn: sqlite3.Connection, path: str | Path) -> int:
    """Import injuries, suspensions and returns.

    `impact` is the share of team strength the absence costs, 0..1. Leave it
    blank and a sensible default for the `kind` is used; put 0.25 on a talisman
    striker and 0.03 on a squad full-back.
    """
    loaded = 0
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            player = (row.get("player") or "").strip()
            kind = (row.get("kind") or "").strip().lower()
            if not player or not kind:
                continue
            team_id = resolve_team(conn, row["team"], row.get("league"))
            if team_id is None:
                continue
            impact = (row.get("impact") or "").strip()
            conn.execute(
                "INSERT INTO team_news (team_id, match_id, player, kind, detail, "
                "impact, source, added_at) VALUES (?,?,?,?,?,?,?,?)",
                (team_id, None, player, kind, (row.get("detail") or "").strip(),
                 float(impact) if impact else IMPACT_DEFAULTS.get(kind, 0.08),
                 "manual", (row.get("date") or datetime.now().date().isoformat())),
            )
            loaded += 1
    return loaded


def load_player_stats(conn: sqlite3.Connection, path: str | Path) -> int:
    """Import per-player season totals (an FBref or Sofascore export works)."""
    loaded = 0
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            player = (row.get("player") or "").strip()
            if not player:
                continue
            team_id = resolve_team(conn, row["team"], row.get("league"))
            if team_id is None:
                continue

            def num(key: str) -> int:
                value = (row.get(key) or "").strip()
                return int(float(value)) if value else 0

            conn.execute(
                "INSERT INTO player_stats (player, team_id, league_code, season, "
                "position, apps, minutes, goals, shots, sot, fouls, yellows, reds) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(player, team_id, season) DO UPDATE SET "
                "apps=excluded.apps, minutes=excluded.minutes, goals=excluded.goals, "
                "shots=excluded.shots, sot=excluded.sot, fouls=excluded.fouls, "
                "yellows=excluded.yellows, reds=excluded.reds, "
                "updated_at=CURRENT_TIMESTAMP",
                (player, team_id, row.get("league"), row.get("season"),
                 row.get("position"), num("apps"), num("minutes"), num("goals"),
                 num("shots"), num("sot"), num("fouls"), num("yellows"), num("reds")),
            )
            loaded += 1
    return loaded
