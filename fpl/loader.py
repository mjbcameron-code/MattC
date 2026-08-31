"""Fetching and assembling everything the scout needs.

Season-level data covers the whole player pool cheaply. Per-match history is
far more expensive - one request per player - so it is fetched only for the
shortlist that matters: your own fifteen plus the leading transfer targets.
That is where the difference between a player who reliably clears the DefCon
threshold and one who managed it once actually shows up.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import rules
from .api import FplApiError, FplClient
from .model import GameState, Pick, Player, Squad


def _pick_gameweek(state: GameState, requested: int | None) -> int:
    if requested:
        return requested
    nxt = state.next_gw
    if nxt:
        return nxt.id
    current = state.current_gw
    return current.id if current else 1


def load_state(client: FplClient) -> GameState:
    bootstrap = client.bootstrap()
    fixtures = client.fixtures()
    if not bootstrap.get("elements"):
        raise FplApiError("bootstrap returned no players — the API shape may have changed")
    return GameState.build(bootstrap, fixtures)


def load_squad(client: FplClient, entry_id: int, state: GameState) -> Squad:
    """Read a manager's current fifteen, bank and transfer state."""
    entry = client.entry(entry_id)
    history = client.entry_history(entry_id)

    # Picks are only published for gameweeks that have started, so fall back
    # to the last gameweek that has one.
    current = state.current_gw
    target_gw = current.id if current else 1
    picks_payload = None
    for gameweek in range(target_gw, 0, -1):
        try:
            picks_payload = client.picks(entry_id, gameweek)
            target_gw = gameweek
            break
        except FplApiError:
            continue
    if picks_payload is None:
        raise FplApiError(
            f"no published squad found for entry {entry_id} — check the team ID is right"
        )

    entry_history = picks_payload.get("entry_history", {}) or {}
    bank = int(entry_history.get("bank", entry.get("last_deadline_bank") or 0))
    value = int(entry_history.get("value", entry.get("last_deadline_value") or 1000))

    chips_used: list = []
    for chip in history.get("chips", []) or []:
        chips_used.append((chip.get("name"), chip.get("event")))

    picks: list[Pick] = []
    for raw in picks_payload.get("picks", []) or []:
        player = state.players.get(int(raw.get("element", 0)))
        if player is None:
            continue
        picks.append(
            Pick(
                player=player,
                position=int(raw.get("position", 15)),
                is_captain=bool(raw.get("is_captain")),
                is_vice=bool(raw.get("is_vice_captain")),
                selling_price=int(raw.get("selling_price", player.cost)),
                purchase_price=int(raw.get("purchase_price", player.cost)),
            )
        )
    picks.sort(key=lambda p: p.position)

    free_transfers = _free_transfers(client, entry_id, picks_payload, entry)

    return Squad(
        entry_id=entry_id,
        manager_name=f"{entry.get('player_first_name', '')} {entry.get('player_last_name', '')}".strip()
        or "Manager",
        team_name=entry.get("name", "My Team"),
        gameweek=target_gw,
        picks=picks,
        bank=bank,
        squad_value=value,
        free_transfers=free_transfers,
        overall_rank=entry.get("summary_overall_rank"),
        total_points=int(entry.get("summary_overall_points") or 0),
        chips_used=chips_used,
    )


def _free_transfers(client: FplClient, entry_id: int, picks_payload: dict, entry: dict) -> int:
    """How many free transfers are in hand, capped at the rolling maximum."""
    # The API exposes this directly in recent seasons; fall back to 1 when it
    # does not, which is the safe assumption.
    for candidate in ("transfers", "entry_history"):
        block = picks_payload.get(candidate)
        if isinstance(block, dict):
            for key in ("limit", "free_transfers", "value"):
                if key in block and block[key] is not None:
                    try:
                        return max(0, min(rules.MAX_ROLLED_TRANSFERS, int(block[key])))
                    except (TypeError, ValueError):
                        pass
    return 1


def _match_defcon_actions(entry: dict, position: int) -> float | None:
    """Defensive actions in a single match, however the API spells them."""
    for key in ("defensive_contribution", "defensive_contributions"):
        if entry.get(key) is not None:
            try:
                return float(entry[key])
            except (TypeError, ValueError):
                pass

    parts = 0.0
    found = False
    for key in ("clearances_blocks_interceptions", "tackles"):
        if entry.get(key) is not None:
            found = True
            try:
                parts += float(entry[key])
            except (TypeError, ValueError):
                pass
    if position in (3, 4) and entry.get("recoveries") is not None:
        found = True
        try:
            parts += float(entry["recoveries"])
        except (TypeError, ValueError):
            pass
    return parts if found else None


def enrich_defcon(client: FplClient, players: list[Player], limit: int = 80) -> int:
    """Count how often each player has actually cleared the DefCon threshold.

    The season payload gives a rate; only the per-match history says whether a
    player clears the bar week in, week out or spikes once and flatters the
    average. Returns the number of players successfully enriched.
    """
    enriched = 0
    for player in players[:limit]:
        if player.position not in rules.DEFCON_ELIGIBLE:
            continue
        try:
            summary = client.element_summary(player.id)
        except FplApiError:
            continue

        threshold = rules.DEFCON_THRESHOLD.get(player.position, 12)
        hits = 0
        played = 0
        values: list[float] = []
        for match in summary.get("history", []) or []:
            if float(match.get("minutes") or 0) < 30:
                continue
            actions = _match_defcon_actions(match, player.position)
            if actions is None:
                continue
            played += 1
            values.append(actions)

        if not played:
            continue

        # If every value is 0 or 2 the field is recording points, not actions.
        if values and all(v in (0.0, 2.0) for v in values):
            hits = sum(1 for v in values if v > 0)
        else:
            hits = sum(1 for v in values if v >= threshold)

        player.matches_hitting_defcon = hits
        if played > player.matches_played:
            player.matches_played = played
        enriched += 1
    return enriched


@dataclass
class LoadResult:
    state: GameState
    squad: Squad | None
    gameweek: int
    enriched: int


def load_all(
    client: FplClient,
    entry_id: int | None,
    gameweek: int | None = None,
    deep: bool = True,
) -> LoadResult:
    state = load_state(client)
    squad = load_squad(client, entry_id, state) if entry_id else None
    target_gw = _pick_gameweek(state, gameweek)

    enriched = 0
    if deep:
        shortlist: list[Player] = list(squad.players) if squad else []
        # Add the most defensively active players in the game, since they are
        # the ones a DefCon-aware model most wants to check by hand.
        others = sorted(
            (
                p for p in state.players.values()
                if p.available and p.minutes >= 90 and p.position in rules.DEFCON_ELIGIBLE
            ),
            key=lambda p: p.defcon90,
            reverse=True,
        )
        seen = {p.id for p in shortlist}
        for player in others:
            if len(shortlist) >= 80:
                break
            if player.id not in seen:
                shortlist.append(player)
                seen.add(player.id)
        enriched = enrich_defcon(client, shortlist)

    return LoadResult(state=state, squad=squad, gameweek=target_gw, enriched=enriched)
