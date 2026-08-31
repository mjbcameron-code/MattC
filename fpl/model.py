"""Normalised domain objects built from the raw FPL payloads.

The API is generous but inconsistent: numbers arrive as strings, new fields
appear between seasons and old ones quietly vanish. Everything here reads
defensively so that a missing field degrades one metric rather than the run.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import rules


def num(source: dict, *names: str, default: float = 0.0) -> float:
    """First readable number among `names`, coerced from whatever we get."""
    for name in names:
        if name not in source:
            continue
        value = source[name]
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


@dataclass
class Team:
    id: int
    name: str
    short_name: str
    strength: int = 3
    attack_home: float = 1100.0
    attack_away: float = 1100.0
    defence_home: float = 1100.0
    defence_away: float = 1100.0

    @classmethod
    def parse(cls, raw: dict) -> "Team":
        return cls(
            id=int(raw.get("id", 0)),
            name=raw.get("name", "Unknown"),
            short_name=raw.get("short_name", "UNK"),
            strength=int(num(raw, "strength", default=3)),
            attack_home=num(raw, "strength_attack_home", default=1100.0),
            attack_away=num(raw, "strength_attack_away", default=1100.0),
            defence_home=num(raw, "strength_defence_home", default=1100.0),
            defence_away=num(raw, "strength_defence_away", default=1100.0),
        )

    def attack(self, home: bool) -> float:
        return self.attack_home if home else self.attack_away

    def defence(self, home: bool) -> float:
        return self.defence_home if home else self.defence_away


@dataclass
class Fixture:
    id: int
    event: int | None
    team_h: int
    team_a: int
    finished: bool = False
    kickoff: str | None = None
    difficulty_h: int = 3
    difficulty_a: int = 3

    @classmethod
    def parse(cls, raw: dict) -> "Fixture":
        event = raw.get("event")
        return cls(
            id=int(raw.get("id", 0)),
            event=int(event) if event is not None else None,
            team_h=int(raw.get("team_h", 0)),
            team_a=int(raw.get("team_a", 0)),
            finished=bool(raw.get("finished", False)),
            kickoff=raw.get("kickoff_time"),
            difficulty_h=int(num(raw, "team_h_difficulty", default=3)),
            difficulty_a=int(num(raw, "team_a_difficulty", default=3)),
        )

    def opponent_of(self, team_id: int) -> int | None:
        if team_id == self.team_h:
            return self.team_a
        if team_id == self.team_a:
            return self.team_h
        return None

    def is_home(self, team_id: int) -> bool:
        return team_id == self.team_h

    def difficulty_for(self, team_id: int) -> int:
        return self.difficulty_h if team_id == self.team_h else self.difficulty_a


@dataclass
class Player:
    id: int
    name: str
    full_name: str
    team_id: int
    position: int
    cost: int                    # tenths of a million
    status: str = "a"
    news: str = ""
    chance_next: float | None = None

    minutes: float = 0.0
    starts: float = 0.0
    total_points: float = 0.0
    points_per_game: float = 0.0
    form: float = 0.0
    selected_by: float = 0.0
    ep_next: float = 0.0

    goals: float = 0.0
    assists: float = 0.0
    clean_sheets: float = 0.0
    goals_conceded: float = 0.0
    saves: float = 0.0
    bonus: float = 0.0
    bps: float = 0.0
    yellow_cards: float = 0.0
    red_cards: float = 0.0

    # Underlying / expected data
    xg: float = 0.0
    xa: float = 0.0
    xgi: float = 0.0
    xgc: float = 0.0
    xg90: float = 0.0
    xa90: float = 0.0
    xgi90: float = 0.0
    xgc90: float = 0.0

    # Defensive actions
    defcon: float = 0.0           # season defensive-contribution actions or points
    defcon90: float = 0.0
    cbi: float = 0.0
    tackles: float = 0.0
    recoveries: float = 0.0

    # Set pieces
    penalties_order: int | None = None
    corners_order: int | None = None
    freekicks_order: int | None = None

    cost_change: float = 0.0
    transfers_in_event: float = 0.0
    transfers_out_event: float = 0.0

    # Filled in later by the analysis layer
    matches_hitting_defcon: int = 0
    matches_played: int = 0
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def parse(cls, raw: dict) -> "Player":
        minutes = num(raw, "minutes")
        player = cls(
            id=int(raw.get("id", 0)),
            name=raw.get("web_name", "Unknown"),
            full_name=f"{raw.get('first_name', '')} {raw.get('second_name', '')}".strip(),
            team_id=int(raw.get("team", 0)),
            position=int(raw.get("element_type", 3)),
            cost=int(num(raw, "now_cost", default=40)),
            status=raw.get("status", "a") or "a",
            news=raw.get("news", "") or "",
            minutes=minutes,
            starts=num(raw, "starts"),
            total_points=num(raw, "total_points"),
            points_per_game=num(raw, "points_per_game"),
            form=num(raw, "form"),
            selected_by=num(raw, "selected_by_percent"),
            ep_next=num(raw, "ep_next"),
            goals=num(raw, "goals_scored"),
            assists=num(raw, "assists"),
            clean_sheets=num(raw, "clean_sheets"),
            goals_conceded=num(raw, "goals_conceded"),
            saves=num(raw, "saves"),
            bonus=num(raw, "bonus"),
            bps=num(raw, "bps"),
            yellow_cards=num(raw, "yellow_cards"),
            red_cards=num(raw, "red_cards"),
            xg=num(raw, "expected_goals"),
            xa=num(raw, "expected_assists"),
            xgi=num(raw, "expected_goal_involvements"),
            xgc=num(raw, "expected_goals_conceded"),
            cbi=num(raw, "clearances_blocks_interceptions"),
            tackles=num(raw, "tackles"),
            recoveries=num(raw, "recoveries"),
            cost_change=num(raw, "cost_change_start"),
            transfers_in_event=num(raw, "transfers_in_event"),
            transfers_out_event=num(raw, "transfers_out_event"),
            raw=raw,
        )

        chance = raw.get("chance_of_playing_next_round")
        player.chance_next = float(chance) if chance is not None else None

        # Per-90 rates: prefer the API's own, fall back to computing them.
        per90 = minutes / 90.0 if minutes > 0 else 0.0
        player.xg90 = num(raw, "expected_goals_per_90") or (player.xg / per90 if per90 else 0.0)
        player.xa90 = num(raw, "expected_assists_per_90") or (player.xa / per90 if per90 else 0.0)
        player.xgi90 = num(raw, "expected_goal_involvements_per_90") or (player.xg90 + player.xa90)
        player.xgc90 = num(raw, "expected_goals_conceded_per_90") or (
            player.xgc / per90 if per90 else 0.0
        )

        # Defensive contributions. The field name has moved around between
        # seasons, so try the known spellings before deriving from raw actions.
        player.defcon = num(raw, "defensive_contribution", "defensive_contributions")
        player.defcon90 = num(raw, "defensive_contribution_per_90", "defensive_contributions_per_90")
        if not player.defcon90:
            actions = player.cbi + player.tackles
            if player.position in (3, 4):
                actions += player.recoveries
            player.defcon90 = actions / per90 if per90 else 0.0

        for attr, key in (
            ("penalties_order", "penalties_order"),
            ("corners_order", "corners_and_indirect_freekicks_order"),
            ("freekicks_order", "direct_freekicks_order"),
        ):
            value = raw.get(key)
            if value is not None:
                try:
                    setattr(player, attr, int(value))
                except (TypeError, ValueError):
                    pass
        return player

    # -- convenience ------------------------------------------------------

    @property
    def price(self) -> float:
        return self.cost / 10.0

    @property
    def position_name(self) -> str:
        return rules.POSITIONS.get(self.position, "?")

    @property
    def available(self) -> bool:
        return self.status not in rules.UNAVAILABLE_STATUSES

    @property
    def start_rate(self) -> float:
        """Share of the team's matches this player has started."""
        if self.matches_played:
            return min(1.0, self.starts / self.matches_played)
        return 0.0

    @property
    def minutes_per_appearance(self) -> float:
        appearances = max(self.starts, 1.0)
        return self.minutes / appearances if self.minutes else 0.0

    @property
    def on_pens(self) -> bool:
        return self.penalties_order is not None and self.penalties_order <= 1


@dataclass
class Gameweek:
    id: int
    name: str
    deadline: str | None
    finished: bool
    is_current: bool
    is_next: bool

    @classmethod
    def parse(cls, raw: dict) -> "Gameweek":
        return cls(
            id=int(raw.get("id", 0)),
            name=raw.get("name", ""),
            deadline=raw.get("deadline_time"),
            finished=bool(raw.get("finished", False)),
            is_current=bool(raw.get("is_current", False)),
            is_next=bool(raw.get("is_next", False)),
        )


@dataclass
class Pick:
    player: Player
    position: int          # 1..15, 1..11 are the starting XI
    is_captain: bool
    is_vice: bool
    selling_price: int
    purchase_price: int

    @property
    def on_bench(self) -> bool:
        return self.position > 11


@dataclass
class Squad:
    entry_id: int
    manager_name: str
    team_name: str
    gameweek: int
    picks: list[Pick]
    bank: int              # tenths
    squad_value: int       # tenths
    free_transfers: int
    overall_rank: int | None
    total_points: int
    chips_used: list[str]

    @property
    def bank_m(self) -> float:
        return self.bank / 10.0

    @property
    def value_m(self) -> float:
        return self.squad_value / 10.0

    @property
    def players(self) -> list[Player]:
        return [pick.player for pick in self.picks]

    @property
    def starters(self) -> list[Pick]:
        return [pick for pick in self.picks if not pick.on_bench]

    @property
    def bench(self) -> list[Pick]:
        return [pick for pick in self.picks if pick.on_bench]

    @property
    def captain(self) -> Pick | None:
        return next((pick for pick in self.picks if pick.is_captain), None)

    def club_counts(self) -> dict[int, int]:
        counts: dict[int, int] = {}
        for player in self.players:
            counts[player.team_id] = counts.get(player.team_id, 0) + 1
        return counts


@dataclass
class GameState:
    """Everything the analysis layer needs, in one normalised bundle."""

    players: dict[int, Player]
    teams: dict[int, Team]
    fixtures: list[Fixture]
    gameweeks: list[Gameweek]

    @property
    def current_gw(self) -> Gameweek | None:
        return next((gw for gw in self.gameweeks if gw.is_current), None)

    @property
    def next_gw(self) -> Gameweek | None:
        nxt = next((gw for gw in self.gameweeks if gw.is_next), None)
        if nxt:
            return nxt
        return next((gw for gw in self.gameweeks if not gw.finished), None)

    def team(self, team_id: int) -> Team:
        return self.teams.get(team_id, Team(id=team_id, name="Unknown", short_name="UNK"))

    def fixtures_for(self, team_id: int, gameweek: int) -> list[Fixture]:
        return [
            fixture
            for fixture in self.fixtures
            if fixture.event == gameweek and team_id in (fixture.team_h, fixture.team_a)
        ]

    @classmethod
    def build(cls, bootstrap: dict, fixtures_raw: list[dict]) -> "GameState":
        teams = {t.id: t for t in (Team.parse(r) for r in bootstrap.get("teams", []))}
        players = {p.id: p for p in (Player.parse(r) for r in bootstrap.get("elements", []))}
        fixtures = [Fixture.parse(r) for r in fixtures_raw]
        gameweeks = [Gameweek.parse(r) for r in bootstrap.get("events", [])]

        # How many league matches each club has actually played, so that
        # start-rate means something in the opening weeks of a season.
        played: dict[int, int] = {}
        for fixture in fixtures:
            if fixture.finished:
                played[fixture.team_h] = played.get(fixture.team_h, 0) + 1
                played[fixture.team_a] = played.get(fixture.team_a, 0) + 1
        for player in players.values():
            player.matches_played = played.get(player.team_id, 0)

        return cls(players=players, teams=teams, fixtures=fixtures, gameweeks=gameweeks)
