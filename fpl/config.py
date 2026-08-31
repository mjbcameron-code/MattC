"""Remembering your team ID, so you type it once.

Looked up in the order most-specific first: the command line, then the
FPL_TEAM_ID environment variable, then a small config file. Whenever an ID is
passed explicitly it is written back, so the second run needs no arguments.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path(
    os.environ.get("FPL_SCOUT_CONFIG_DIR", Path.home() / ".config" / "fpl-scout")
)
CONFIG_FILE = CONFIG_DIR / "config.json"


def _read() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def load_team_id() -> int | None:
    """The remembered team ID, if there is one."""
    from_env = os.environ.get("FPL_TEAM_ID")
    if from_env:
        try:
            return int(from_env.strip())
        except ValueError:
            pass

    stored = _read().get("team_id")
    if stored is not None:
        try:
            return int(stored)
        except (TypeError, ValueError):
            pass
    return None


def save_team_id(team_id: int) -> Path | None:
    """Remember a team ID for next time. Failure here is never fatal."""
    data = _read()
    if data.get("team_id") == team_id:
        return None
    data["team_id"] = team_id
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(data, indent=2))
        return CONFIG_FILE
    except OSError:
        return None
