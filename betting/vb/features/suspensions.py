"""Suspensions inferred from the match data itself, with no feed required.

Injury lists sit behind a paid plan on every provider worth using. Suspensions
are different: a red card is a matter of public record in the result, and a
sending-off means the team is without that player for the next match. That is
derivable from data we already hold, for nothing.

What this cannot do is name the player. football-data.co.uk records that a team
finished with ten men, not who was dismissed, so the entry says "a player" and
carries a modest impact. Knowing a side is one man light is still worth more
than assuming a full squad, and a sending-off in the previous match is one of
the few absences that is certain rather than reported.

Yellow-card accumulation is deliberately not attempted: it needs per-player
counts, which no free feed publishes for these divisions, and guessing would be
worse than the silence.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

SOURCE = "derived-red-card"

# A straight red is usually a one-match ban, sometimes three. Without knowing
# who was sent off or what for, this is deliberately conservative.
RED_CARD_IMPACT = 0.07


def derive_suspensions(
    conn: sqlite3.Connection,
    as_of: datetime | None = None,
    lookback_days: int = 21,
) -> int:
    """Record, for each recent sending-off, an absence in that team's next match.

    Returns the number of entries written. Running it twice writes nothing the
    second time.
    """
    as_of = as_of or datetime.now()
    since = (as_of - timedelta(days=lookback_days)).isoformat()

    rows = conn.execute(
        "SELECT id, league_code, kickoff, home_id, away_id, "
        "COALESCE(hr, 0) AS home_reds, COALESCE(ar, 0) AS away_reds "
        "FROM matches WHERE status = 'played' AND kickoff >= ? AND kickoff <= ? "
        "AND (COALESCE(hr, 0) > 0 OR COALESCE(ar, 0) > 0) ORDER BY kickoff",
        (since, as_of.isoformat()),
    ).fetchall()

    written = 0
    for match in rows:
        for team_id, reds in ((match["home_id"], match["home_reds"]),
                              (match["away_id"], match["away_reds"])):
            if not reds:
                continue
            next_match = conn.execute(
                "SELECT id, kickoff FROM matches WHERE status = 'scheduled' "
                "AND (home_id = ? OR away_id = ?) AND kickoff > ? "
                "ORDER BY kickoff LIMIT 1",
                (team_id, team_id, match["kickoff"]),
            ).fetchone()
            if next_match is None:
                continue        # nothing scheduled yet, so nothing to apply it to
            already = conn.execute(
                "SELECT id FROM team_news WHERE team_id = ? AND match_id = ? "
                "AND source = ?",
                (team_id, next_match["id"], SOURCE),
            ).fetchone()
            if already:
                continue
            plural = "players" if reds > 1 else "a player"
            conn.execute(
                "INSERT INTO team_news (team_id, match_id, player, kind, detail, "
                "impact, source, added_at) VALUES (?,?,?,?,?,?,?,?)",
                (team_id, next_match["id"], plural, "suspension",
                 f"sent off in the previous match ({match['kickoff'][:10]})",
                 RED_CARD_IMPACT * reds, SOURCE, match["kickoff"][:10]),
            )
            written += 1
    return written


def describe(conn: sqlite3.Connection, match_id: int) -> list[str]:
    """Any derived absences attached to one fixture, for the write-up."""
    rows = conn.execute(
        "SELECT t.name, n.detail, n.player FROM team_news n "
        "JOIN teams t ON t.id = n.team_id WHERE n.match_id = ? AND n.source = ?",
        (match_id, SOURCE),
    ).fetchall()
    return [f"{r['name']} are without {r['player']} {r['detail']}" for r in rows]
