"""Shared HTTP fetching with an on-disk cache.

Every remote call goes through here so that a re-run costs nothing and so the
whole pipeline can be exercised offline from cached files.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import requests

from ..config import CACHE_DIR, ensure_dirs

USER_AGENT = "value-bets/1.0 (+personal betting research)"
DEFAULT_TIMEOUT = 30


class FetchError(RuntimeError):
    pass


def _cache_path(url: str, suffix: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    stem = "".join(ch if ch.isalnum() else "-" for ch in url.split("/")[-1])[:40]
    return CACHE_DIR / f"{stem}-{digest}{suffix}"


def fetch_text(
    url: str,
    max_age: int = 6 * 3600,
    suffix: str = ".txt",
    params: dict | None = None,
    force: bool = False,
    headers_out: dict | None = None,
) -> str:
    """GET ``url`` as text, serving from cache when the copy is fresh enough.

    Raises :class:`FetchError` with an actionable message on failure — some
    environments block the football data hosts outright, and the caller needs
    to know that is what happened rather than seeing a bare traceback.
    """
    ensure_dirs()
    full = url if not params else url + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    path = _cache_path(full, suffix)
    if not force and path.exists() and (time.time() - path.stat().st_mtime) < max_age:
        return path.read_text(encoding="utf-8", errors="replace")

    try:
        resp = requests.get(
            url, params=params, timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
    except requests.RequestException as exc:
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
        raise FetchError(
            f"could not reach {url}: {exc}. If this machine sits behind a "
            f"restrictive proxy, download the file by hand and drop it in "
            f"{CACHE_DIR}."
        ) from exc

    if resp.status_code != 200:
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
        raise FetchError(f"{url} returned HTTP {resp.status_code}")

    # utf-8-sig, not utf-8: these files are served with a byte-order mark, which
    # plain utf-8 leaves on the front of the first column name. Every row then
    # has a "Div" that reads as None, and a whole fixture list is skipped in
    # silence.
    if headers_out is not None:
        headers_out.update(resp.headers)
    text = resp.content.decode("utf-8-sig", errors="replace")
    path.write_text(text, encoding="utf-8")
    return text


def fetch_json(url: str, max_age: int = 900, params: dict | None = None,
               force: bool = False, headers_out: dict | None = None):
    import json

    return json.loads(fetch_text(url, max_age=max_age, suffix=".json", params=params,
                                 force=force, headers_out=headers_out))


def cached_copies() -> list[Path]:
    ensure_dirs()
    return sorted(CACHE_DIR.glob("*"))
