"""Configuration loading: leagues, settings and filesystem paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = Path(os.environ.get("VB_DATA_DIR", ROOT / "data"))
CACHE_DIR = DATA_DIR / "cache"
REPORT_DIR = Path(os.environ.get("VB_REPORT_DIR", ROOT / "reports"))
DB_PATH = Path(os.environ.get("VB_DB", DATA_DIR / "betting.db"))


@dataclass(frozen=True)
class League:
    code: str
    name: str
    country: str
    tier: int
    football_data: str | None = None
    odds_api: str | None = None
    understat: str | None = None
    openfootball: str | None = None
    enabled: bool = True

    @property
    def is_uefa(self) -> bool:
        return self.country == "Europe"


class Settings:
    """Thin attribute-style wrapper over settings.yaml."""

    def __init__(self, raw: dict[str, Any]):
        self._raw = raw

    def __getitem__(self, key: str) -> Any:
        return self._raw[key]

    def get(self, path: str, default: Any = None) -> Any:
        """Fetch a nested value with a dotted path, e.g. 'bankroll.max_stake_pts'."""
        node: Any = self._raw
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def market_blend(self, tier: int) -> float:
        """Weight given to the model (vs the market) for a league of this tier."""
        table = self.get("model.market_blend", {}) or {}
        return float(table.get(str(tier), table.get(tier, 0.35)))

    @property
    def raw(self) -> dict[str, Any]:
        return self._raw


@lru_cache(maxsize=1)
def load_leagues() -> dict[str, League]:
    with open(CONFIG_DIR / "leagues.yaml") as fh:
        raw = yaml.safe_load(fh)
    out: dict[str, League] = {}
    for entry in raw["leagues"]:
        allowed = League.__dataclass_fields__.keys()
        out[entry["code"]] = League(**{k: v for k, v in entry.items() if k in allowed})
    return out


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    with open(CONFIG_DIR / "settings.yaml") as fh:
        return Settings(yaml.safe_load(fh))


def enabled_leagues() -> list[League]:
    return [lg for lg in load_leagues().values() if lg.enabled]


def league(code: str) -> League:
    try:
        return load_leagues()[code]
    except KeyError:
        raise KeyError(
            f"Unknown league code {code!r}. Known codes: "
            + ", ".join(sorted(load_leagues()))
        ) from None


def ensure_dirs() -> None:
    for path in (DATA_DIR, CACHE_DIR, REPORT_DIR):
        path.mkdir(parents=True, exist_ok=True)
