"""Live bookmaker prices from the-odds-api.com.

This is where Sky Bet, Bet365, Paddy Power, William Hill, Ladbrokes and the
rest come from. Set ODDS_API_KEY in the environment (a free key allows 500
requests a month, which is plenty for a weekly tipping cycle if you stick to
the leagues you actually bet).

Market keys differ by sport and change over time, so nothing here assumes a
market exists: unavailable markets are reported and skipped rather than
crashing the run. `vb probe-markets` shows what a given league currently
offers.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable

from ..config import enabled_leagues, league as get_league, load_settings
from ..repo import upsert_match, upsert_odds
from .http import FetchError, fetch_json

API_BASE = "https://api.the-odds-api.com/v4"

# our market name  <-  the-odds-api market key
MARKET_KEYS = {
    "h2h": "h2h",
    "totals": "totals",
    "ah": "spreads",
    "btts": "btts",
    "double_chance": "double_chance",
    "dnb": "draw_no_bet",
    "team_totals": "team_totals",
    "alt_totals": "alternate_totals",
    "corners": "alternate_totals_corners",
    "player_sot": "player_shots_on_target",
    "player_shots": "player_shots",
    "player_card": "player_to_receive_card",
    "player_goal": "player_goal_scorer_anytime",
}

CORE_MARKETS = ["h2h", "totals", "ah"]
EXTRA_MARKETS = ["btts", "double_chance", "dnb", "team_totals", "alt_totals"]
PLAYER_MARKETS = ["player_sot", "player_shots", "player_card", "player_goal"]


class MissingApiKey(RuntimeError):
    pass


def api_key() -> str:
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key:
        raise MissingApiKey(
            "ODDS_API_KEY is not set. Get a free key at https://the-odds-api.com "
            "and export it, or enter prices by hand with `vb odds-template`."
        )
    return key


def list_sports(force: bool = False) -> list[dict[str, Any]]:
    return fetch_json(f"{API_BASE}/sports/", params={"apiKey": api_key()},
                      max_age=24 * 3600, force=force)


def verify_sport_keys() -> dict[str, str]:
    """Check configured odds_api keys against what the API actually offers.

    Returns {league_code: status} where status is 'ok', 'missing (did you mean
    X?)' or 'not configured'. Keys drift over time, so this is worth running
    at the start of a season.
    """
    available = {s["key"] for s in list_sports()}
    report: dict[str, str] = {}
    for lg in enabled_leagues():
        if not lg.odds_api:
            report[lg.code] = "not configured — manual prices only"
        elif lg.odds_api in available:
            report[lg.code] = "ok"
        else:
            near = [k for k in available if k.startswith("soccer_")
                    and any(w in k for w in lg.name.lower().split())]
            hint = f" (did you mean: {', '.join(sorted(near)[:3])})" if near else ""
            report[lg.code] = f"missing key {lg.odds_api!r}{hint}"
    return report


def _fetch_odds(sport_key: str, markets: Iterable[str], regions: str, force: bool):
    keys = ",".join(MARKET_KEYS[m] for m in markets if m in MARKET_KEYS)
    return fetch_json(
        f"{API_BASE}/sports/{sport_key}/odds/",
        params={
            "apiKey": api_key(),
            "regions": regions,
            "markets": keys,
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        },
        max_age=900,        # 15 minutes: fresh enough, kind to the quota
        force=force,
    )


def _selection_for(outcome_name: str, home: str, away: str) -> str | None:
    name = (outcome_name or "").strip()
    low = name.lower()
    if low in {"draw", "tie"}:
        return "draw"
    if low == "over":
        return "over"
    if low == "under":
        return "under"
    if low == "yes":
        return "yes"
    if low == "no":
        return "no"
    if name == home:
        return "home"
    if name == away:
        return "away"
    return None


def load_league_odds(
    conn: sqlite3.Connection,
    league_code: str,
    season: str,
    markets: list[str] | None = None,
    force: bool = False,
) -> tuple[int, int]:
    """Pull current prices for one league. Returns (events seen, prices stored)."""
    lg = get_league(league_code)
    if not lg.odds_api:
        return (0, 0)
    settings = load_settings()
    regions = settings.get("bookmakers.region", "uk")
    markets = markets or CORE_MARKETS

    try:
        events = _fetch_odds(lg.odds_api, markets, regions, force)
    except FetchError as exc:
        raise FetchError(f"{league_code}: {exc}") from exc
    if isinstance(events, dict) and events.get("message"):
        raise FetchError(f"{league_code}: odds API said {events['message']!r}")

    taken_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    stored = 0
    for event in events:
        home, away = event.get("home_team"), event.get("away_team")
        if not home or not away:
            continue
        kickoff = event.get("commence_time") or taken_at
        match_id = upsert_match(
            conn, league_code, season, kickoff.replace("Z", ""), home, away,
            source="odds-api",
        )
        for book in event.get("bookmakers", []):
            book_key = book.get("key", "unknown")
            for market in book.get("markets", []):
                our_market = _reverse_market(market.get("key", ""))
                if our_market is None:
                    continue
                for outcome in market.get("outcomes", []):
                    price = outcome.get("price")
                    if not price or price <= 1.0:
                        continue
                    subject = outcome.get("description")   # player props
                    selection = _selection_for(outcome.get("name", ""), home, away)
                    if selection is None and subject:
                        selection = (outcome.get("name") or "").lower()
                    if selection is None:
                        continue
                    if subject:
                        selection = f"{subject}|{selection}"
                    upsert_odds(
                        conn, match_id, book_key, our_market, selection,
                        float(price), outcome.get("point"), taken_at=taken_at,
                    )
                    stored += 1
    return (len(events), stored)


def _reverse_market(api_key_name: str) -> str | None:
    for ours, theirs in MARKET_KEYS.items():
        if theirs == api_key_name:
            return ours
    return None


def probe_markets(league_code: str) -> dict[str, str]:
    """Ask the API, one market at a time, which markets this league serves."""
    lg = get_league(league_code)
    if not lg.odds_api:
        return {"_": "no odds-api key configured for this league"}
    out: dict[str, str] = {}
    for name in [*CORE_MARKETS, *EXTRA_MARKETS, *PLAYER_MARKETS]:
        try:
            data = _fetch_odds(lg.odds_api, [name], load_settings().get("bookmakers.region", "uk"), False)
            if isinstance(data, dict) and data.get("message"):
                out[name] = f"unavailable: {data['message']}"
            else:
                books = {b["key"] for ev in data for b in ev.get("bookmakers", [])}
                out[name] = f"ok — {len(data)} events, {len(books)} books" if data else "no events"
        except FetchError as exc:
            out[name] = f"unavailable ({exc})"
    return out


def load_scores(
    conn: sqlite3.Connection,
    league_code: str,
    season: str,
    days_from: int = 3,
    force: bool = True,
) -> int:
    """Pull recent finished scores. This is how UEFA results get in.

    football-data.co.uk publishes no Champions/Europa League file, so for those
    two competitions the odds API scores endpoint (or a manual CSV) is the only
    way results reach the database.
    """
    lg = get_league(league_code)
    if not lg.odds_api:
        return 0
    data = fetch_json(
        f"{API_BASE}/sports/{lg.odds_api}/scores/",
        params={"apiKey": api_key(), "daysFrom": max(1, min(3, days_from)), "dateFormat": "iso"},
        max_age=600,
        force=force,
    )
    if isinstance(data, dict):
        raise FetchError(f"{league_code}: odds API said {data.get('message')!r}")

    updated = 0
    for event in data:
        if not event.get("completed"):
            continue
        home, away = event.get("home_team"), event.get("away_team")
        scores = {s.get("name"): s.get("score") for s in (event.get("scores") or [])}
        try:
            fthg, ftag = int(scores[home]), int(scores[away])
        except (KeyError, TypeError, ValueError):
            continue
        upsert_match(
            conn, league_code, season,
            (event.get("commence_time") or "").replace("Z", ""), home, away,
            fthg=fthg, ftag=ftag, status="played", source="odds-api-scores",
        )
        updated += 1
    return updated
