"""football-data.co.uk ingest — the backbone of the whole database.

One CSV per league per season carries results, shots, shots on target,
corners, fouls, cards, the referee, and the prices a dozen bookmakers went
off at (opening and closing). That is enough to fit the match models, to
build the corner and card models, and to measure closing line value.

Note on books: the set of bookmakers in these files changes over the years, so
both the current columns (Bet365, Sky Bet, BetVictor, Betfair Exchange) and the
older ones (Pinnacle, William Hill, Bet&Win) are read. Any column prefix not
listed in BOOKS is ignored rather than guessed at — football-data.co.uk's
notes.txt defines what each one means.
"""

from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime
from typing import Iterator

from ..config import league as get_league
from ..repo import upsert_match, upsert_odds

BASE = "https://www.football-data.co.uk/mmz4281"

# CSV column prefix -> bookmaker name we store.
BOOKS = {
    # Current columns
    "B365": "bet365",
    "SKB": "skybet",
    "BV": "betvictor",
    "BFE": "betfair_ex",
    "BW": "bwin",
    # Older columns, still present in historical season files
    "BF": "betfair_ex",
    "PS": "pinnacle",
    "P": "pinnacle",
    "WH": "williamhill",
    "VC": "betvictor",
    "1XB": "1xbet",
    "IW": "interwetten",
    "LB": "ladbrokes",
    "SB": "sportingbet",
    "SJ": "stanjames",
    "GB": "gamebookers",
    "BS": "bluesquare",
    "Max": "market_max",
    "Avg": "market_avg",
}

STAT_COLUMNS = {
    "FTHG": "fthg", "FTAG": "ftag", "HTHG": "hthg", "HTAG": "htag",
    "HS": "hs", "AS": "as", "HST": "hst", "AST": "ast",
    "HC": "hc", "AC": "ac", "HF": "hf", "AF": "af",
    "HY": "hy", "AY": "ay", "HR": "hr", "AR": "ar",
    "Referee": "referee",
}


def season_code(season: str) -> str:
    """'2025/26' -> '2526' (the form football-data.co.uk uses in its paths)."""
    start, end = season.replace("-", "/").split("/")
    start = start[-2:]
    end = end[-2:] if len(end) > 2 else end
    return f"{int(start):02d}{int(end):02d}"


def season_label(code: str) -> str:
    return f"20{code[:2]}/{code[2:]}"


def csv_url(league_code: str, season: str) -> str:
    lg = get_league(league_code)
    if not lg.football_data:
        raise ValueError(f"{league_code} has no football-data.co.uk feed")
    return f"{BASE}/{season_code(season)}/{lg.football_data}.csv"


def _num(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _int(value: str | None) -> int | None:
    num = _num(value)
    return None if num is None else int(num)


def parse_date(date_str: str, time_str: str | None = None) -> str:
    """football-data uses dd/mm/yy and dd/mm/yyyy interchangeably."""
    date_str = (date_str or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            day = datetime.strptime(date_str, fmt)
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"unrecognised date {date_str!r}")
    clock = (time_str or "").strip() or "15:00"
    try:
        hour, minute = (int(x) for x in clock.split(":")[:2])
    except ValueError:
        hour, minute = 15, 0
    return day.replace(hour=hour, minute=minute).isoformat(timespec="seconds")


def iter_rows(text: str) -> Iterator[dict[str, str]]:
    """Rows with clean header names.

    A file hand-downloaded into the cache, or fetched by something that does not
    strip the byte-order mark, arrives with "\ufeffDiv" as its first column.
    Normalising here means a stray mark can never silently cost a whole file
    again.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    for row in reader:
        cleaned = {(k or "").strip().lstrip("\ufeff"): v for k, v in row.items()}
        if not (cleaned.get("HomeTeam") or "").strip():
            continue          # trailing blank lines are common in these files
        yield cleaned


def _odds_from_row(row: dict[str, str]) -> list[tuple[str, str, str, float | None, float]]:
    """Extract (bookmaker, market, selection, line, price) tuples from a row."""
    out: list[tuple[str, str, str, float | None, float]] = []
    for prefix, book in BOOKS.items():
        for closing in ("", "C"):
            name = book if not closing else f"{book}_close"
            # 1X2
            trio = [_num(row.get(f"{prefix}{closing}{s}")) for s in ("H", "D", "A")]
            if all(p and p > 1.0 for p in trio):
                for sel, price in zip(("home", "draw", "away"), trio):
                    out.append((name, "h2h", sel, None, price))
            # Over/under 2.5 goals
            over = _num(row.get(f"{prefix}{closing}>2.5"))
            under = _num(row.get(f"{prefix}{closing}<2.5"))
            if over and under and over > 1.0 and under > 1.0:
                out.append((name, "totals", "over", 2.5, over))
                out.append((name, "totals", "under", 2.5, under))
            # Asian handicap (line is in the shared AHh / AHCh column)
            line = _num(row.get("AHCh" if closing else "AHh"))
            ah_home = _num(row.get(f"{prefix}{closing}AHH"))
            ah_away = _num(row.get(f"{prefix}{closing}AHA"))
            if line is not None and ah_home and ah_away:
                out.append((name, "ah", "home", line, ah_home))
                out.append((name, "ah", "away", -line, ah_away))
    return out


def load_csv_text(
    conn: sqlite3.Connection,
    league_code: str,
    season: str,
    text: str,
    with_odds: bool = True,
) -> int:
    """Parse one football-data CSV into the database. Returns matches written."""
    count = 0
    for row in iter_rows(text):
        kickoff = parse_date(row.get("Date", ""), row.get("Time"))
        stats: dict = {"source": "football-data"}
        for src, dest in STAT_COLUMNS.items():
            value = row.get(src)
            if dest == "referee":
                if value and value.strip():
                    stats[dest] = value.strip()
            else:
                num = _int(value)
                if num is not None:
                    stats[dest] = num
        match_id = upsert_match(
            conn, league_code, season, kickoff,
            row["HomeTeam"].strip(), row["AwayTeam"].strip(), **stats,
        )
        if with_odds:
            taken = kickoff[:10]
            for book, market, selection, line, price in _odds_from_row(row):
                upsert_odds(
                    conn, match_id, book, market, selection, price, line,
                    taken_at=taken, is_closing=book.endswith("_close"),
                )
        count += 1
    return count


def load_season(
    conn: sqlite3.Connection,
    league_code: str,
    season: str,
    force: bool = False,
    with_odds: bool = True,
) -> int:
    from .http import fetch_text

    url = csv_url(league_code, season)
    # Completed seasons never change; the current one is refreshed twice a day.
    text = fetch_text(url, max_age=6 * 3600, suffix=".csv", force=force)
    return load_csv_text(conn, league_code, season, text, with_odds=with_odds)


def recent_seasons(n: int, ending: str | None = None) -> list[str]:
    """The n most recent season labels, most recent last."""
    if ending:
        end_year = int(ending.split("/")[0])
    else:
        today = datetime.now()
        end_year = today.year if today.month >= 7 else today.year - 1
    return [f"{y}/{str(y + 1)[-2:]}" for y in range(end_year - n + 1, end_year + 1)]


FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"


def load_fixtures(
    conn: sqlite3.Connection,
    season: str,
    league_codes: list[str] | None = None,
    force: bool = True,
) -> dict[str, int]:
    """Load the next week or so of fixtures, with prices, for every league at once.

    football-data.co.uk publishes one combined fixtures file covering all its
    divisions with opening prices attached. It is the reason this whole system
    works with no API key at all for the English, Scottish, German, Italian and
    Spanish leagues — only the European competitions need another source.
    """
    from ..config import load_leagues
    from .http import fetch_text

    text = fetch_text(FIXTURES_URL, max_age=3600, suffix=".csv", force=force)
    by_div = {lg.football_data: lg.code for lg in load_leagues().values()
              if lg.football_data}
    wanted = set(league_codes) if league_codes else None

    counts: dict[str, int] = {}
    for row in iter_rows(text):
        div = (row.get("Div") or "").strip()
        league_code = by_div.get(div)
        if not league_code or (wanted and league_code not in wanted):
            continue
        kickoff = parse_date(row.get("Date", ""), row.get("Time"))
        match_id = upsert_match(
            conn, league_code, season, kickoff,
            row["HomeTeam"].strip(), row["AwayTeam"].strip(),
            status="scheduled", source="football-data-fixtures",
        )
        for book, market, selection, line, price in _odds_from_row(row):
            if book.endswith("_close"):
                continue
            upsert_odds(conn, match_id, book, market, selection, price, line,
                        taken_at=datetime.now().isoformat(timespec="seconds"))
        counts[league_code] = counts.get(league_code, 0) + 1
    return counts
