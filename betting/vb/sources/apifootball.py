"""API-Football (API-Sports) — fast results, injuries, match stats, player data.

This is the paid-for-if-you-want-it feed that fills the gaps football-data.co.uk
structurally cannot: results within minutes of full time, the European
competitions, injury lists, and player-level match data.

Three things shape how this module is written.

**Requests are rationed, and the cost is per fixture.** Asking for every result
on a Saturday costs one request; asking for the player statistics of every
Saturday fixture costs one *each*. A free allowance disappears in a single
afternoon if nothing is counting. So every call goes through :class:`Budget`,
which reads the allowance back from the API's own response headers and stops
before it runs out — loudly, naming what it did not fetch, rather than quietly
returning half a card.

**League ids are numbers and must never be guessed.** A wrong id does not
error; it silently returns a different competition. Ids are discovered by
querying the league list and matching on country and name, the result is cached,
and `vb apifootball check` prints it for a human to confirm.

**The account may be either shopfront.** The same data is sold direct and
through RapidAPI, with different auth headers. Which one you have is detected
from the key rather than configured.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from ..config import CACHE_DIR, enabled_leagues, ensure_dirs, load_leagues
from ..db import get_setting, set_setting
from ..repo import resolve_team, token_similarity

DIRECT_BASE = "https://v3.football.api-sports.io"
RAPID_BASE = "https://api-football-v1.p.rapidapi.com/v3"
RAPID_HOST = "api-football-v1.p.rapidapi.com"
USER_AGENT = "value-bets/1.0 (personal betting research)"

# What .env.example ships with. Someone copying the file and forgetting to edit
# it produces a key-shaped string that is not a key.
PLACEHOLDER_VALUES = {"paste-your-key-here", "your-key-here", "changeme", ""}

LEAGUE_MAP_KEY = "apifootball.league_map"
BUDGET_KEY = "apifootball.budget"


class ApiFootballError(RuntimeError):
    pass


class BudgetExhausted(ApiFootballError):
    """Raised when the daily allowance is spent, so callers can stop cleanly."""


class MissingKey(ApiFootballError):
    pass


# ---------------------------------------------------------------------------
# budget
# ---------------------------------------------------------------------------
@dataclass
class Budget:
    """Counts requests and refuses to spend past the daily allowance.

    ``limit`` and ``remaining`` are learned from the API's own headers on the
    first reply, so nothing has to be configured by hand and the numbers stay
    right if the plan changes.
    """

    limit: int | None = None
    remaining: int | None = None
    used_this_run: int = 0
    reserve: int = 5          # never spend the last few — leaves room to settle
    max_this_run: int | None = None
    skipped: list[str] = field(default_factory=list)

    def check(self, what: str) -> None:
        if self.max_this_run is not None and self.used_this_run >= self.max_this_run:
            raise BudgetExhausted(
                f"stopped after {self.used_this_run} requests this run (the --budget "
                f"limit) before fetching {what}"
            )
        if self.remaining is not None and self.remaining <= self.reserve:
            raise BudgetExhausted(
                f"only {self.remaining} requests left on today's allowance "
                f"(holding {self.reserve} back); did not fetch {what}"
            )

    def record(self, headers: dict) -> None:
        self.used_this_run += 1
        limit = _header_int(headers, "x-ratelimit-requests-limit")
        remaining = _header_int(headers, "x-ratelimit-requests-remaining")
        if limit is not None:
            self.limit = limit
        if remaining is not None:
            self.remaining = remaining
        elif self.remaining is not None:
            self.remaining -= 1

    def note_skip(self, what: str) -> None:
        self.skipped.append(what)

    def describe(self) -> str:
        if self.limit is None:
            return f"{self.used_this_run} requests made this run (allowance unknown)"
        return (f"{self.used_this_run} requests this run · "
                f"{self.remaining if self.remaining is not None else '?'} of "
                f"{self.limit} left today")


def _header_int(headers: dict, name: str) -> int | None:
    for key, value in headers.items():
        if key.lower() == name:
            try:
                return int(str(value).strip())
            except (TypeError, ValueError):
                return None
    return None


# ---------------------------------------------------------------------------
# client
# ---------------------------------------------------------------------------
class Client:
    """Thin wrapper over the API, with caching, budgeting and clear errors."""

    def __init__(self, key: str | None = None, budget: Budget | None = None,
                 timeout: int = 25, via: str | None = None):
        import os

        self.key = (key or os.environ.get("API_FOOTBALL_KEY", "")).strip()
        if not self.key:
            raise MissingKey(
                "API_FOOTBALL_KEY is not set. Sign up at https://api-football.com, "
                "copy the key from your dashboard, and export it:\n"
                "    export API_FOOTBALL_KEY='...'\n"
                "Keep it in the environment: a key pasted into a chat, an issue or a "
                "commit is a key that needs regenerating."
            )
        self.budget = budget or Budget()
        self.timeout = timeout
        self.key_source = "the environment" if _key_from_environment() else ".env"
        if self.key.lower() in PLACEHOLDER_VALUES:
            raise MissingKey(
                f"API_FOOTBALL_KEY is still the placeholder from .env.example "
                f"({self.key!r}). Open .env and replace it with the key from your "
                "api-football.com dashboard."
            )
        self.forced = via in ("direct", "rapidapi")
        if self.forced:
            self.via_rapidapi = via == "rapidapi"
        else:
            self.via_rapidapi = _looks_like_rapidapi(self.key)
        self.base = RAPID_BASE if self.via_rapidapi else DIRECT_BASE
        self.last_errors: list[str] = []

    def key_fingerprint(self) -> str:
        """Enough of the key to recognise it, not enough to use it.

        The commonest cause of a rejected key is the file holding a different
        one from the dashboard — an old key after regenerating, a half-paste, a
        stray character. Showing the first and last few characters and the
        length settles that in a glance, and is safe to share when asking for
        help.
        """
        key = self.key
        shape = f"{len(key)} characters, from {self.key_source}"
        if len(key) < 12:
            return f"{key[:2]}… ({shape}) — that looks too short"
        return f"{key[:4]}…{key[-4:]} ({shape})"

    @property
    def shopfront(self) -> str:
        name = "RapidAPI" if self.via_rapidapi else "api-football.com (direct)"
        return f"{name} [forced]" if self.forced else name

    def headers(self) -> dict[str, str]:
        # Identify ourselves properly. The default python-requests user agent is
        # a common trigger for a blanket 403 from the CDN in front of this API,
        # long before the key is ever looked at.
        common = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if self.via_rapidapi:
            return {**common, "x-rapidapi-key": self.key, "x-rapidapi-host": RAPID_HOST}
        return {**common, "x-apisports-key": self.key}

    def get(self, endpoint: str, params: dict | None = None,
            max_age: int = 0, label: str | None = None) -> list[dict]:
        """One call. Returns the ``response`` array, or raises with the API's reason."""
        params = {k: v for k, v in (params or {}).items() if v is not None}
        what = label or f"{endpoint} {params}"
        cached = _read_cache(endpoint, params, max_age)
        if cached is not None:
            return cached

        self.budget.check(what)
        url = f"{self.base}/{endpoint.lstrip('/')}"
        try:
            response = requests.get(url, params=params, headers=self.headers(),
                                    timeout=self.timeout)
        except requests.RequestException as exc:
            raise ApiFootballError(f"could not reach {url}: {exc}") from exc

        self.budget.record(dict(response.headers))

        if response.status_code == 429:
            raise BudgetExhausted("the API says you are out of requests for now (HTTP 429)")
        if response.status_code != 200:
            raise ApiFootballError(self._explain(response))

        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiFootballError(f"{endpoint} did not return JSON") from exc

        errors = payload.get("errors")
        if errors:
            # The API reports problems in the body with a 200 status, and the
            # shape varies between a dict and a list.
            messages = list(errors.values()) if isinstance(errors, dict) else list(errors)
            messages = [str(m) for m in messages if m]
            if messages:
                self.last_errors = messages
                raise ApiFootballError(f"{endpoint}: {'; '.join(messages)}")

        data = payload.get("response")
        if data is None:
            raise ApiFootballError(f"{endpoint}: no 'response' field in the reply")
        if isinstance(data, dict):
            data = [data]
        _write_cache(endpoint, params, data)
        return data

    # What each shopfront says, and what it means. These messages are specific
    # enough to identify the problem exactly, which beats a list of guesses.
    KNOWN_MESSAGES = [
        ("not subscribed", 
         "that is RapidAPI's wording for a key it does not recognise as subscribed. "
         "Either this key is from api-football.com — in which case run with "
         "--via direct — or it is a RapidAPI key whose free plan you have not "
         "subscribed to yet (open the API-Football page on RapidAPI and press "
         "Subscribe; the Basic plan is free)"),
        ("invalid api key",
         "the key itself was not accepted — check .env against your dashboard"),
        ("missing application key",
         "no key reached the API, so .env is not being read; check it sits in the "
         "betting folder and the line has no spaces around the ="),
        ("account is not active",
         "the account exists but is not activated — confirm the address in the "
         "sign-up email"),
    ]

    def _explain(self, response) -> str:
        """Turn a failed reply into something actionable.

        The reason is almost always in the body, and throwing it away in favour
        of a status code — as this first did — leaves nothing to act on. 401 and
        403 mean different things here and get different advice.
        """
        detail = self._body_message(response)
        code = response.status_code
        lines = [f"HTTP {code} from {self.shopfront}"]
        if detail:
            lines.append(f"the API said: {detail.rstrip('.')}")
        for needle, advice in self.KNOWN_MESSAGES:
            if needle in detail.lower():
                lines.append(advice)
                return ". ".join(lines)
        if code == 401:
            lines.append("that is a missing or invalid key — check .env for a typo, "
                         "and that you copied the whole thing")
        elif code == 403:
            lines.append(
                "403 usually means the key is real but not yet usable. In order of "
                "likelihood: the account email has not been confirmed; the key was "
                "regenerated and .env still holds the old one; the account is "
                "actually a RapidAPI one (re-run with --via rapidapi); or something "
                "on your network is blocking the host"
            )
        return ". ".join(lines)

    @staticmethod
    def _body_message(response) -> str:
        """Pull a human-readable reason out of whatever the server returned."""
        try:
            payload = response.json()
        except ValueError:
            text = (response.text or "").strip()
            # An HTML error page means something in front of the API answered,
            # not the API itself.
            if text.lower().startswith(("<!doctype", "<html")):
                return "an HTML error page, so something between you and the API " \
                       "answered rather than the API itself"
            return text[:200]
        if isinstance(payload, dict):
            for key in ("message", "error", "errors"):
                value = payload.get(key)
                if isinstance(value, dict):
                    value = "; ".join(f"{k}: {v}" for k, v in value.items())
                if value:
                    return str(value)[:200]
        return ""

    def status(self) -> dict:
        """Account and quota, and the cheapest possible check that the key works."""
        rows = self.get("status", label="account status")
        return rows[0] if rows else {}


def _looks_like_rapidapi(key: str) -> bool:
    """RapidAPI keys are longer and carry a distinctive suffix.

    This is a guess that the caller can override; a wrong guess produces a clear
    401 rather than silent nonsense, and the error message says how to switch.
    """
    return len(key) > 45 or key.endswith("jsn") or "msh" in key[:6]


# ---------------------------------------------------------------------------
# a small on-disk cache, so a re-run costs nothing
# ---------------------------------------------------------------------------
def _cache_file(endpoint: str, params: dict) -> Path:
    import hashlib

    ensure_dirs()
    stem = endpoint.strip("/").replace("/", "-")
    digest = hashlib.sha256(
        (stem + json.dumps(params, sort_keys=True)).encode()
    ).hexdigest()[:16]
    return CACHE_DIR / f"apifootball-{stem}-{digest}.json"


def _read_cache(endpoint: str, params: dict, max_age: int):
    if max_age <= 0:
        return None
    path = _cache_file(endpoint, params)
    if not path.exists() or (time.time() - path.stat().st_mtime) > max_age:
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _write_cache(endpoint: str, params: dict, data) -> None:
    try:
        _cache_file(endpoint, params).write_text(json.dumps(data))
    except (OSError, TypeError):
        pass


# ---------------------------------------------------------------------------
# league discovery
# ---------------------------------------------------------------------------
# Their names for our competitions differ enough that a plain equality test
# fails: we say "EFL Championship", they say "Championship". These are hints
# for the matcher, not assertions — the match is still scored and reported.
NAME_HINTS = {
    "E0": ("England", ["Premier League"]),
    "E1": ("England", ["Championship"]),
    "E2": ("England", ["League One"]),
    "E3": ("England", ["League Two"]),
    "EC": ("England", ["National League"]),
    "SC0": ("Scotland", ["Premiership"]),
    "SC1": ("Scotland", ["Championship"]),
    "SC2": ("Scotland", ["League One"]),
    "SC3": ("Scotland", ["League Two"]),
    "D1": ("Germany", ["Bundesliga", "1. Bundesliga"]),
    "D2": ("Germany", ["2. Bundesliga"]),
    "I1": ("Italy", ["Serie A"]),
    "I2": ("Italy", ["Serie B"]),
    "SP1": ("Spain", ["La Liga", "Primera Division"]),
    "SP2": ("Spain", ["Segunda Division", "La Liga 2"]),
    "UCL": ("World", ["UEFA Champions League", "Champions League"]),
    "UEL": ("World", ["UEFA Europa League", "Europa League"]),
}

# Below this the match is reported but not used without a human saying so.
CONFIDENT_MATCH = 0.82


@dataclass
class LeagueMatch:
    code: str
    api_id: int | None
    api_name: str = ""
    api_country: str = ""
    score: float = 0.0
    season: int | None = None
    note: str = ""
    # The near misses, so an ambiguous match is visible rather than silent.
    alternatives: list[tuple[str, int, float]] = field(default_factory=list)

    @property
    def confident(self) -> bool:
        return self.api_id is not None and self.score >= CONFIDENT_MATCH


def _country_matches(ours: str, theirs: str) -> bool:
    ours, theirs = (ours or "").lower(), (theirs or "").lower()
    if ours == theirs:
        return True
    # UEFA competitions are filed under "World" rather than a country.
    return ours in ("europe", "world") and theirs in ("world", "europe")


def discover_leagues(client: Client, codes: list[str] | None = None,
                     season: int | None = None) -> dict[str, LeagueMatch]:
    """Map our league codes onto their numeric ids. Costs one request.

    Matching is on country first, then name, using the same abbreviation-aware
    comparison that resolves club names. Every match carries a score, and a
    weak one is reported rather than used.
    """
    catalogue = client.get("leagues", max_age=7 * 24 * 3600, label="the league list")
    wanted = codes or [lg.code for lg in enabled_leagues()]
    leagues = load_leagues()
    out: dict[str, LeagueMatch] = {}

    for code in wanted:
        league = leagues.get(code)
        if league is None:
            continue
        country_hint, name_hints = NAME_HINTS.get(code, (league.country, [league.name]))
        best = LeagueMatch(code=code, api_id=None)
        scored: list[tuple[str, int, float]] = []
        for entry in catalogue:
            info = entry.get("league") or {}
            country = (entry.get("country") or {}).get("name", "")
            if not _country_matches(country_hint, country):
                continue
            their_name = info.get("name") or ""
            score = max(
                (token_similarity(hint, their_name) for hint in name_hints),
                default=0.0,
            )
            # An exact hit on any hint beats everything.
            if any(their_name.lower() == hint.lower() for hint in name_hints):
                score = 1.0
            if info.get("id") is not None and score > 0.4:
                scored.append((their_name, int(info["id"]), score))
            if score > best.score:
                best = LeagueMatch(
                    code=code, api_id=info.get("id"), api_name=their_name,
                    api_country=country, score=score,
                    season=_current_season(entry, season),
                )
        scored.sort(key=lambda row: -row[2])
        best.alternatives = [row for row in scored if row[1] != best.api_id][:2]
        if best.api_id is None:
            best.note = f"nothing in {country_hint} resembled {name_hints[0]!r}"
        elif not best.confident:
            best.note = "weak match — confirm before trusting it"
        elif best.alternatives and best.alternatives[0][2] >= CONFIDENT_MATCH:
            best.note = "another competition scored nearly as well — check it"
        out[code] = best
    return out


def _current_season(entry: dict, preferred: int | None) -> int | None:
    seasons = entry.get("seasons") or []
    if preferred:
        for season in seasons:
            if season.get("year") == preferred:
                return preferred
    for season in seasons:
        if season.get("current"):
            return season.get("year")
    return seasons[-1].get("year") if seasons else None


def save_league_map(conn: sqlite3.Connection, matches: dict[str, LeagueMatch]) -> None:
    payload = {
        code: {"id": m.api_id, "name": m.api_name, "country": m.api_country,
               "score": round(m.score, 3), "season": m.season}
        for code, m in matches.items() if m.api_id is not None
    }
    set_setting(conn, LEAGUE_MAP_KEY, json.dumps(payload))


def load_league_map(conn: sqlite3.Connection) -> dict[str, dict]:
    raw = get_setting(conn, LEAGUE_MAP_KEY)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def league_id(conn: sqlite3.Connection, code: str) -> int | None:
    """The confirmed id for one of our leagues, or None if it was never mapped.

    An explicit `api_football` value in leagues.yaml always wins, so a bad
    automatic match can be overridden by hand.
    """
    league = load_leagues().get(code)
    override = getattr(league, "api_football", None) if league else None
    if override:
        return int(override)
    entry = load_league_map(conn).get(code)
    return entry.get("id") if entry else None


def season_year(conn: sqlite3.Connection, code: str, season: str) -> int:
    """'2026/27' -> 2026, which is how they label a season."""
    entry = load_league_map(conn).get(code) or {}
    if entry.get("season"):
        return int(entry["season"])
    return int(str(season).split("/")[0])


# ---------------------------------------------------------------------------
# fixtures and results
# ---------------------------------------------------------------------------
# Their status codes. Anything not finished is a fixture, not a result.
FINISHED = {"FT", "AET", "PEN"}
ABANDONED = {"PST", "CANC", "ABD", "AWD", "WO", "SUSP", "INT"}


def _fixture_rows(entry: dict) -> dict | None:
    """Flatten one of their fixture objects into the columns we store."""
    fixture = entry.get("fixture") or {}
    teams = entry.get("teams") or {}
    goals = entry.get("goals") or {}
    score = entry.get("score") or {}
    home = (teams.get("home") or {}).get("name")
    away = (teams.get("away") or {}).get("name")
    kickoff = fixture.get("date")
    if not home or not away or not kickoff:
        return None
    status = ((fixture.get("status") or {}).get("short") or "").upper()
    row: dict[str, Any] = {
        "api_id": fixture.get("id"),
        "home": home,
        "away": away,
        # Their timestamps carry a timezone offset; we store naive local ISO.
        "kickoff": str(kickoff).replace("Z", "+00:00")[:19],
        "referee": fixture.get("referee"),
        "stage": (entry.get("league") or {}).get("round"),
        "status": status,
        "finished": status in FINISHED,
        "abandoned": status in ABANDONED,
    }
    if row["finished"]:
        row["fthg"], row["ftag"] = goals.get("home"), goals.get("away")
        halftime = score.get("halftime") or {}
        row["hthg"], row["htag"] = halftime.get("home"), halftime.get("away")
    return row


def load_fixtures(
    conn: sqlite3.Connection,
    client: Client,
    season: str,
    date: str | None = None,
    codes: list[str] | None = None,
    league_season: int | None = None,
    max_age: int = 300,
) -> dict[str, int]:
    """Load fixtures and results.

    Asking by date fetches every league we follow in a single request, which is
    why the daily results sweep is nearly free. Asking by league costs one
    request per league but reaches the whole season.
    """
    from ..repo import find_match_near, upsert_match

    mapping = load_league_map(conn)
    by_api_id = {}
    for code in (codes or list(mapping)):
        api_id = league_id(conn, code)
        if api_id is not None:
            by_api_id[int(api_id)] = code
    if not by_api_id:
        raise ApiFootballError(
            "no leagues have been mapped yet — run `vb apifootball check` first"
        )

    batches: list[list[dict]] = []
    if date:
        batches.append(client.get("fixtures", {"date": date}, max_age=max_age,
                                  label=f"fixtures on {date}"))
    else:
        for api_id, code in by_api_id.items():
            year = league_season or season_year(conn, code, season)
            try:
                batches.append(client.get(
                    "fixtures", {"league": api_id, "season": year},
                    max_age=max_age, label=f"{code} fixtures"))
            except BudgetExhausted:
                client.budget.note_skip(f"{code} fixtures")
                break

    counts: dict[str, int] = {}
    for batch in batches:
        for entry in batch:
            api_league = ((entry.get("league") or {}).get("id"))
            code = by_api_id.get(api_league)
            if code is None:
                continue                      # a competition we do not follow
            row = _fixture_rows(entry)
            if row is None or row["abandoned"]:
                continue

            existing = find_match_near(conn, code, row["home"], row["away"],
                                       row["kickoff"])
            stats: dict[str, Any] = {"source": "api-football"}
            if row["api_id"]:
                stats["api_fixture_id"] = int(row["api_id"])
            if row["referee"]:
                stats["referee"] = row["referee"]
            if row["stage"]:
                stats["stage"] = row["stage"]
            if row["finished"] and row.get("fthg") is not None:
                stats["fthg"], stats["ftag"] = row["fthg"], row["ftag"]
                if row.get("hthg") is not None:
                    stats["hthg"], stats["htag"] = row["hthg"], row["htag"]
                stats["status"] = "played"

            if existing is not None and existing["fthg"] is not None:
                # Already have the result from a richer feed. Still record their
                # fixture id, which is the key to asking for its statistics.
                if row["api_id"] and existing["api_fixture_id"] is None:
                    conn.execute("UPDATE matches SET api_fixture_id = ? WHERE id = ?",
                                 (int(row["api_id"]), existing["id"]))
                    counts[code] = counts.get(code, 0) + 1
                continue
            if existing is not None:
                sets = ", ".join(f'"{k}" = ?' for k in stats if k != "source")
                if sets:
                    conn.execute(
                        f"UPDATE matches SET {sets} WHERE id = ?",
                        (*[v for k, v in stats.items() if k != "source"], existing["id"]),
                    )
            else:
                upsert_match(conn, code, season, row["kickoff"], row["home"],
                             row["away"], **stats)
            counts[code] = counts.get(code, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# injuries — the piece with no free alternative anywhere
# ---------------------------------------------------------------------------
# Their `type` field, mapped onto ours. "Missing Fixture" is a definite absence;
# "Questionable" is a doubt, which should move a price less.
INJURY_KINDS = {
    "missing fixture": ("injury", 0.10),
    "questionable": ("doubt", 0.05),
}

# Reasons that are a suspension rather than an injury — worth distinguishing,
# because a suspended player is certainly out and an injured one may not be.
SUSPENSION_WORDS = ("suspend", "red card", "yellow cards", "ban")


def _classify(kind: str, reason: str) -> tuple[str, float]:
    reason_lower = (reason or "").lower()
    if any(word in reason_lower for word in SUSPENSION_WORDS):
        return ("suspension", 0.10)
    return INJURY_KINDS.get((kind or "").lower(), ("injury", 0.08))


def load_injuries(
    conn: sqlite3.Connection,
    client: Client,
    season: str,
    codes: list[str] | None = None,
    date: str | None = None,
    max_age: int = 3600,
) -> dict[str, int]:
    """Pull injury and suspension lists into `team_news`.

    One request per league. This is the single most valuable thing this feed
    adds: team news moves a price further than any refinement of the model, and
    until now it had to be typed in by hand.

    The importance of each absence is left at a default, because the API says
    who is out but not what they are worth. Raising the impact for a talisman
    is a judgement call the tool should not pretend to make — edit the row, or
    the defaults in vb/sources/manual.py, when it matters.
    """
    codes = codes or [lg.code for lg in enabled_leagues()]
    counts: dict[str, int] = {}
    today = date or datetime.now().date().isoformat()

    for code in codes:
        api_id = league_id(conn, code)
        if api_id is None:
            continue
        year = season_year(conn, code, season)
        try:
            rows = client.get("injuries", {"league": api_id, "season": year},
                              max_age=max_age, label=f"{code} injuries")
        except BudgetExhausted:
            client.budget.note_skip(f"{code} injuries")
            break
        except ApiFootballError:
            # Some plans do not serve injuries for every competition; that is a
            # coverage limit, not a failure of the run.
            client.budget.note_skip(f"{code} injuries (not covered)")
            continue

        written = 0
        for entry in rows:
            player = ((entry.get("player") or {}).get("name") or "").strip()
            team = ((entry.get("team") or {}).get("name") or "").strip()
            if not player or not team:
                continue
            fixture_date = ((entry.get("fixture") or {}).get("date") or "")[:10]
            # Only news attached to a fixture that has not happened yet.
            if fixture_date and fixture_date < today:
                continue
            team_id = resolve_team(conn, team, code, source="api-football")
            if team_id is None:
                continue
            kind, impact = _classify(entry.get("type"), entry.get("reason"))
            already = conn.execute(
                "SELECT id FROM team_news WHERE team_id = ? AND player = ? "
                "AND added_at >= ?",
                (team_id, player, (datetime.now() - timedelta(days=7)).date().isoformat()),
            ).fetchone()
            if already:
                continue
            conn.execute(
                "INSERT INTO team_news (team_id, match_id, player, kind, detail, "
                "impact, source, added_at) VALUES (?,?,?,?,?,?,?,?)",
                (team_id, None, player, kind, (entry.get("reason") or "").strip(),
                 impact, "api-football", today),
            )
            written += 1
        counts[code] = written
    return counts


# ---------------------------------------------------------------------------
# per-match statistics — shots, corners, cards, sometimes xG
# ---------------------------------------------------------------------------
STAT_NAMES = {
    "shots on goal": ("hst", "ast"),
    "total shots": ("hs", "as"),
    "corner kicks": ("hc", "ac"),
    "fouls": ("hf", "af"),
    "yellow cards": ("hy", "ay"),
    "red cards": ("hr", "ar"),
    "expected_goals": ("home_xg", "away_xg"),
    "expected goals": ("home_xg", "away_xg"),
}


def _stat_value(raw: Any) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip().rstrip("%")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_statistics(
    conn: sqlite3.Connection,
    client: Client,
    fixtures: list[tuple[int, int]],
    max_age: int = 7 * 24 * 3600,
) -> int:
    """Fill in shots, corners and cards for matches that lack them.

    Costs one request per fixture, which is the expensive end of this API — so
    the caller decides which matches are worth it, and the budget stops the run
    rather than silently fetching a subset.

    ``fixtures`` is a list of (our match id, their fixture id).
    """
    updated = 0
    for match_id, api_fixture_id in fixtures:
        try:
            rows = client.get("fixtures/statistics", {"fixture": api_fixture_id},
                              max_age=max_age, label=f"stats for fixture {api_fixture_id}")
        except BudgetExhausted:
            client.budget.note_skip(f"statistics for {len(fixtures) - updated} more matches")
            break
        except ApiFootballError:
            continue
        if len(rows) < 2:
            continue

        values: dict[str, float] = {}
        for side_index, side in enumerate(rows[:2]):
            for stat in side.get("statistics") or []:
                columns = STAT_NAMES.get((stat.get("type") or "").strip().lower())
                if not columns:
                    continue
                value = _stat_value(stat.get("value"))
                if value is None:
                    continue
                values[columns[side_index]] = value
        if not values:
            continue
        sets = ", ".join(f'"{k}" = ?' for k in values)
        conn.execute(f"UPDATE matches SET {sets} WHERE id = ?",
                     (*values.values(), match_id))
        updated += 1
    return updated


# ---------------------------------------------------------------------------
# the diagnostic
# ---------------------------------------------------------------------------
def check(conn: sqlite3.Connection, client: Client, season: str,
          save: bool = True) -> dict:
    """Verify the key, map the leagues, and report — without printing the key.

    Two requests. The output is designed to be pasted back to someone helping
    you: it names competitions, counts and errors, and contains no credential.
    """
    report: dict[str, Any] = {
        "shopfront": client.shopfront,
        "key": client.key_fingerprint(),
        "errors": [],
    }
    # A direct key is 32 hex characters; a RapidAPI one is much longer. A
    # mismatch here explains a rejection before any request is made.
    if not client.via_rapidapi and len(client.key) != 32:
        report["key_warning"] = (
            f"a direct api-football.com key is normally 32 characters, and this "
            f"one is {len(client.key)} — check .env for a partial paste or extra "
            "characters"
        )
    elif client.via_rapidapi and len(client.key) < 40:
        report["key_warning"] = (
            f"a RapidAPI key is normally 50 characters or so, and this one is "
            f"{len(client.key)} — it looks like a direct api-football.com key, so "
            "try --via direct"
        )

    try:
        status = client.status()
    except ApiFootballError as exc:
        report["errors"].append(str(exc))
        report["ok"] = False
        return report

    subscription = status.get("subscription") or {}
    requests_info = status.get("requests") or {}
    report["ok"] = True
    report["plan"] = subscription.get("plan")
    report["plan_active"] = subscription.get("active")
    report["plan_ends"] = subscription.get("end")
    report["requests_today"] = requests_info.get("current")
    report["requests_limit"] = requests_info.get("limit_day")
    if client.budget.limit is None and requests_info.get("limit_day"):
        client.budget.limit = int(requests_info["limit_day"])
        used = int(requests_info.get("current") or 0)
        client.budget.remaining = client.budget.limit - used

    try:
        matches = discover_leagues(client, season=int(str(season).split("/")[0]))
    except ApiFootballError as exc:
        report["errors"].append(str(exc))
        report["leagues"] = {}
        return report

    if save:
        save_league_map(conn, matches)
    report["leagues"] = matches
    report["budget"] = client.budget.describe()
    report["unmatched"] = [code for code, m in matches.items() if not m.confident]
    return report


def matches_needing_statistics(
    conn: sqlite3.Connection, days: int = 14, limit: int = 20,
    codes: list[str] | None = None,
) -> list[tuple[int, int]]:
    """Played matches we hold a fixture id for but no shot data.

    These are the matches where a request actually buys something — mostly the
    lower Scottish divisions and the National League, where football-data.co.uk
    publishes goals and little else.
    """
    sql = ("SELECT id, api_fixture_id FROM matches WHERE status = 'played' "
           "AND api_fixture_id IS NOT NULL AND hst IS NULL "
           "AND match_date >= date('now', ?)")
    params: list[Any] = [f"-{int(days)} days"]
    if codes:
        sql += f" AND league_code IN ({','.join('?' * len(codes))})"
        params += codes
    sql += " ORDER BY match_date DESC LIMIT ?"
    params.append(int(limit))
    return [(r["id"], r["api_fixture_id"]) for r in conn.execute(sql, params)]


def _key_from_environment() -> bool:
    """True when the key came from a real environment variable, not the file.

    Worth reporting: a stale `export` in a shell profile silently overrides an
    updated .env, and that is a confusing half-hour if you cannot see it.
    """
    import os

    from ..config import ENV_LOADED

    return bool(os.environ.get("API_FOOTBALL_KEY")) and "API_FOOTBALL_KEY" not in ENV_LOADED
