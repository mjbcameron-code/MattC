"""The 2026/27 Fantasy Premier League ruleset.

Every number the engine uses to project points lives here, so that when the
rules move the model moves with them. Verified against the Premier League's
2026/27 rule announcements.
"""

from __future__ import annotations

SEASON = "2026/27"

# Squad composition
SQUAD_SIZE = 15
BUDGET_TENTHS = 1000  # £100.0m, prices are held in tenths of a million
MAX_PER_CLUB = 3
SQUAD_SHAPE = {1: 2, 2: 5, 3: 5, 4: 3}  # GK, DEF, MID, FWD

# Valid starting XI bounds by position
XI_MIN = {1: 1, 2: 3, 3: 2, 4: 1}
XI_MAX = {1: 1, 2: 5, 3: 5, 4: 3}
XI_SIZE = 11

# Transfers
MAX_ROLLED_TRANSFERS = 5
HIT_COST = 4  # points deducted per extra transfer

POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}

# --- Scoring -------------------------------------------------------------

GOAL_POINTS = {1: 10, 2: 6, 3: 5, 4: 4}
ASSIST_POINTS = 3
CLEAN_SHEET_POINTS = {1: 4, 2: 4, 3: 1, 4: 0}
APPEARANCE_60_POINTS = 2
APPEARANCE_SUB_POINTS = 1
SAVES_PER_POINT = 3
GOALS_CONCEDED_PER_MINUS = 2  # GK/DEF lose 1 per 2 conceded
YELLOW_CARD_POINTS = -1
RED_CARD_POINTS = -3
PENALTY_MISS_POINTS = -2
OWN_GOAL_POINTS = -2

# --- Defensive contributions (DefCon) ------------------------------------
# Unchanged for 2026/27. Two points, capped at two per match.
DEFCON_POINTS = 2
DEFCON_THRESHOLD = {
    2: 10,  # DEF: clearances + blocks + interceptions + tackles
    3: 12,  # MID: the above plus ball recoveries
    4: 12,  # FWD: as midfielders
}
# Goalkeepers cannot earn defensive contribution points.
DEFCON_ELIGIBLE = (2, 3, 4)

# --- Bonus points system -------------------------------------------------
# 2026/27 change: one BPS per THREE clearances/blocks/interceptions
# (previously one per two), to reduce overlap with DefCon points and lift
# goalkeepers, full-backs and attackers up the bonus standings.
BPS_CBI_DIVISOR = 3
BONUS_AWARDS = (3, 2, 1)

# --- Chips ---------------------------------------------------------------
# Two sets of four. The first set expires at the Gameweek 19 deadline and
# cannot be carried into the second half of the season.
CHIP_NAMES = ("wildcard", "freehit", "3xc", "bboost")
CHIP_LABELS = {
    "wildcard": "Wildcard",
    "freehit": "Free Hit",
    "3xc": "Triple Captain",
    "bboost": "Bench Boost",
}
FIRST_HALF_LAST_GW = 19  # first-set chips must be played BEFORE the GW19 deadline
TOTAL_GAMEWEEKS = 38

# --- Discipline ----------------------------------------------------------
# Five yellow cards before the GW19 cut-off triggers a one-match ban.
YELLOWS_FOR_BAN = 5
YELLOW_BAN_CUTOFF_GW = 19

# --- Status codes on the player payload ----------------------------------
STATUS_LABELS = {
    "a": "Available",
    "d": "Doubtful",
    "i": "Injured",
    "s": "Suspended",
    "u": "Unavailable",
    "n": "Ineligible",
}
UNAVAILABLE_STATUSES = ("i", "s", "u", "n")
