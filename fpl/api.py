"""Client for the public Fantasy Premier League API.

Uses only the standard library so the scout runs anywhere Python does.
Responses are cached on disk with a short TTL, because a single run touches
the same endpoints repeatedly and the FPL servers do not deserve the traffic.

Nothing here requires authentication: every endpoint used is the same public
JSON the fantasy site itself reads.
"""

from __future__ import annotations

import gzip
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE = "https://fantasy.premierleague.com/api"

DEFAULT_CACHE = Path(os.environ.get("FPL_SCOUT_CACHE", Path.home() / ".cache" / "fpl-scout"))
USER_AGENT = "fpl-scout/1.0 (+personal fantasy analysis)"


class FplApiError(RuntimeError):
    """Raised when the FPL API cannot be reached or returns nonsense."""


class FplClient:
    """Reads the public FPL endpoints, with a disk cache in front."""

    def __init__(
        self,
        cache_dir: Path | str = DEFAULT_CACHE,
        ttl_seconds: int = 900,
        offline: bool = False,
        timeout: int = 30,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.ttl = ttl_seconds
        self.offline = offline
        self.timeout = timeout
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # -- plumbing ---------------------------------------------------------

    def _cache_path(self, key: str) -> Path:
        safe = key.strip("/").replace("/", "_").replace("?", "_").replace("=", "-")
        return self.cache_dir / f"{safe}.json"

    def _read_cache(self, key: str, ignore_ttl: bool = False) -> Any | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        if not ignore_ttl and (time.time() - path.stat().st_mtime) > self.ttl:
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _write_cache(self, key: str, payload: Any) -> None:
        try:
            self._cache_path(key).write_text(json.dumps(payload))
        except OSError:
            pass  # a cache we cannot write is an inconvenience, not a failure

    def get(self, path: str, ttl: int | None = None) -> Any:
        """Fetch `path` relative to the API root, via cache where possible."""
        cached = self._read_cache(path) if ttl != 0 else None
        if cached is not None:
            return cached

        if self.offline:
            stale = self._read_cache(path, ignore_ttl=True)
            if stale is not None:
                return stale
            raise FplApiError(f"offline mode and nothing cached for {path}")

        url = f"{BASE}/{path.lstrip('/')}"
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                request = urllib.request.Request(
                    url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                    if response.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                payload = json.loads(raw.decode("utf-8"))
                self._write_cache(path, payload)
                return payload
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    raise FplApiError(f"not found: {url}") from exc
                last_error = exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                last_error = exc
            if attempt < 3:
                time.sleep(2 ** attempt)

        stale = self._read_cache(path, ignore_ttl=True)
        if stale is not None:
            return stale
        raise FplApiError(f"could not fetch {url}: {last_error}")

    # -- endpoints --------------------------------------------------------

    def bootstrap(self) -> dict:
        """Players, teams, gameweeks and game settings."""
        return self.get("bootstrap-static/")

    def fixtures(self) -> list[dict]:
        """Every fixture in the season, played and unplayed."""
        payload = self.get("fixtures/")
        return payload if isinstance(payload, list) else []

    def entry(self, entry_id: int) -> dict:
        """Manager summary: name, overall rank, squad value, bank."""
        return self.get(f"entry/{entry_id}/")

    def entry_history(self, entry_id: int) -> dict:
        """Season-by-gameweek history, past seasons and chips played."""
        return self.get(f"entry/{entry_id}/history/")

    def picks(self, entry_id: int, gameweek: int) -> dict:
        """The fifteen picked for a gameweek, plus bank and transfer state."""
        return self.get(f"entry/{entry_id}/event/{gameweek}/picks/")

    def transfers(self, entry_id: int) -> list[dict]:
        payload = self.get(f"entry/{entry_id}/transfers/")
        return payload if isinstance(payload, list) else []

    def element_summary(self, element_id: int) -> dict:
        """Per-match history and upcoming fixtures for one player."""
        return self.get(f"element-summary/{element_id}/", ttl=self.ttl * 4)

    def league_standings(self, league_id: int, page: int = 1) -> dict:
        return self.get(f"leagues-classic/{league_id}/standings/?page_standings={page}")

    def live(self, gameweek: int) -> dict:
        return self.get(f"event/{gameweek}/live/", ttl=60)
