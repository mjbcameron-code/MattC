"""A synthetic league, for testing the engine and for demonstrating the app.

Everything here is generated, not real. It exists so the pipeline can be
exercised end to end without touching the network, and so the interface can
be looked at before a team ID is plugged in. Player names are invented and
clubs are placeholders precisely so that nothing in here can be mistaken for
live Fantasy Premier League data.
"""

from __future__ import annotations

import random

CLUBS = [
    ("Ashfield", "ASH", 1340), ("Brookvale", "BRK", 1310), ("Calderton", "CAL", 1285),
    ("Dunmoor", "DUN", 1260), ("Eastmere", "EAS", 1235), ("Fallowfield", "FAL", 1210),
    ("Granby", "GRA", 1185), ("Harlow Vale", "HRV", 1160), ("Ironbridge", "IRN", 1140),
    ("Kestrel Park", "KES", 1120), ("Langden", "LAN", 1100), ("Merrick", "MER", 1080),
    ("Northgate", "NOR", 1060), ("Oakhurst", "OAK", 1040), ("Pentland", "PEN", 1020),
    ("Quarrydale", "QUA", 1000), ("Ravensmoor", "RAV", 980), ("Stanwick", "STA", 960),
    ("Thornbury", "THO", 940), ("Westhaven", "WES", 920),
]

FIRST = ["Alex", "Ben", "Callum", "Dan", "Eli", "Femi", "Gus", "Hugo", "Idris", "Jonah",
         "Kai", "Luca", "Mateo", "Noah", "Omar", "Pedro", "Quinn", "Rafa", "Sami", "Theo"]
LAST = ["Ambrose", "Barker", "Castell", "Dowd", "Ellery", "Fenwick", "Gale", "Hartley",
        "Ines", "Joslin", "Keane", "Lindqvist", "Morrow", "Nyland", "Okafor", "Pryce",
        "Quill", "Reyes", "Sandoval", "Traore", "Underwood", "Varga", "Whitlock", "Yorke"]


def build(seed: int = 7) -> tuple[dict, list[dict], dict, dict, dict]:
    """Return (bootstrap, fixtures, entry, history, picks) for a fake season."""
    rng = random.Random(seed)
    played_gws = 3
    current_gw = 3

    teams = []
    for index, (name, short, strength) in enumerate(CLUBS, start=1):
        teams.append({
            "id": index, "name": name, "short_name": short,
            "strength": min(5, max(1, round((strength - 900) / 110))),
            "strength_attack_home": strength + 40, "strength_attack_away": strength - 30,
            "strength_defence_home": strength + 30, "strength_defence_away": strength - 40,
        })

    elements = []
    element_id = 0
    # Unique surnames, so no two generated players share a display name.
    name_pool = [f"{last}" for last in LAST] + [
        f"{last}{suffix}" for suffix in ("son", "ley", "wood", "field", "ton", "worth",
                                         "by", "ridge", "mont", "hall", "stead", "combe",
                                         "brook", "dale", "crest", "shaw", "burn", "well",
                                         "mere", "gate")
        for last in LAST
    ]
    rng.shuffle(name_pool)
    name_iter = iter(name_pool)
    for team in teams:
        quality = (team["strength_attack_home"] - 900) / 480.0  # 0..1
        shape = [(1, 2), (2, 7), (3, 8), (4, 4)]
        for position, count in shape:
            for slot in range(count):
                element_id += 1
                nailed = slot < {1: 1, 2: 4, 3: 4, 4: 2}[position]
                minutes = rng.randint(240, 270) if nailed else rng.randint(0, 150)
                starts = round(minutes / 90)

                base_price = {1: 45, 2: 45, 3: 50, 4: 55}[position]
                price = base_price + int(quality * {1: 10, 2: 20, 3: 60, 4: 75}[position] * (1.1 if nailed else 0.4))
                price += rng.randint(-3, 5)

                per90 = minutes / 90 if minutes else 0
                attack_rate = quality * {1: 0.0, 2: 0.10, 3: 0.45, 4: 0.70}[position]
                xg = round(max(0.0, rng.gauss(attack_rate * 0.6, 0.15)) * per90, 2)
                xa = round(max(0.0, rng.gauss(attack_rate * 0.4, 0.12)) * per90, 2)

                defensive_rate = {1: 0.0, 2: rng.uniform(6, 13), 3: rng.uniform(5, 14), 4: rng.uniform(2, 8)}[position]
                actions = round(defensive_rate * per90)
                cbi = round(actions * (0.6 if position == 2 else 0.3))
                tackles = round(actions * (0.4 if position == 2 else 0.3))
                recoveries = actions - cbi - tackles if position in (3, 4) else 0

                status, news, chance = "a", "", None
                roll = rng.random()
                if roll > 0.94:
                    status, news, chance = "i", "Hamstring injury - expected back in 3 weeks", 0
                elif roll > 0.89:
                    status, news, chance = "d", "Knock - assessed ahead of the weekend", 50

                surname = next(name_iter)
                elements.append({
                    "id": element_id, "web_name": surname,
                    "first_name": rng.choice(FIRST), "second_name": surname,
                    "team": team["id"], "element_type": position, "now_cost": price,
                    "status": status, "news": news, "chance_of_playing_next_round": chance,
                    "minutes": minutes, "starts": starts,
                    "total_points": max(0, round(minutes / 90 * rng.uniform(1, 7))),
                    "points_per_game": round(rng.uniform(1, 7), 1),
                    "form": round(rng.uniform(0, 7), 1),
                    "selected_by_percent": round(max(0.1, rng.gauss(8, 12)), 1),
                    "ep_next": round(rng.uniform(1, 8), 1),
                    "goals_scored": round(xg * rng.uniform(0.6, 1.4)),
                    "assists": round(xa * rng.uniform(0.6, 1.4)),
                    "clean_sheets": rng.randint(0, played_gws),
                    "goals_conceded": rng.randint(0, 6),
                    "saves": rng.randint(6, 18) if position == 1 else 0,
                    "bonus": rng.randint(0, 6), "bps": rng.randint(0, 90),
                    "yellow_cards": rng.choice([0, 0, 0, 1, 1, 2, 4]),
                    "red_cards": 0,
                    "expected_goals": xg, "expected_assists": xa,
                    "expected_goal_involvements": round(xg + xa, 2),
                    "expected_goals_conceded": round(rng.uniform(0.6, 2.2) * per90, 2),
                    "clearances_blocks_interceptions": cbi, "tackles": tackles,
                    "recoveries": recoveries,
                    "penalties_order": 1 if (position == 4 and slot == 0 and rng.random() > 0.5) else None,
                    "corners_and_indirect_freekicks_order": 1 if (position == 3 and slot == 0) else None,
                    "direct_freekicks_order": None,
                    "cost_change_start": rng.choice([-3, -1, 0, 0, 1, 2, 4]),
                    "transfers_in_event": rng.randint(0, 90000),
                    "transfers_out_event": rng.randint(0, 90000),
                })

    events = []
    for gameweek in range(1, 39):
        events.append({
            "id": gameweek, "name": f"Gameweek {gameweek}",
            "deadline_time": f"2026-{8 + gameweek // 5:02d}-{(gameweek * 7) % 28 + 1:02d}T11:00:00Z",
            "finished": gameweek <= played_gws,
            "is_current": gameweek == current_gw,
            "is_next": gameweek == current_gw + 1,
        })

    # A simple rotation that gives every club a fixture each week, then a
    # deliberate double and blank later on so the chip logic has something
    # to find.
    fixtures = []
    fixture_id = 0
    ids = [t["id"] for t in teams]
    for gameweek in range(1, 39):
        rotated = ids[:1] + ids[1:][(gameweek - 1) % (len(ids) - 1):] + ids[1:][: (gameweek - 1) % (len(ids) - 1)]
        half = len(rotated) // 2
        for home, away in zip(rotated[:half], reversed(rotated[half:])):
            if gameweek % 2 == 0:
                home, away = away, home
            fixture_id += 1
            fixtures.append({
                "id": fixture_id, "event": gameweek, "team_h": home, "team_a": away,
                "finished": gameweek <= played_gws,
                "kickoff_time": f"2026-{8 + gameweek // 5:02d}-{(gameweek * 7) % 28 + 2:02d}T14:00:00Z",
                "team_h_difficulty": min(5, max(1, 6 - round((teams[away - 1]["strength"])))),
                "team_a_difficulty": min(5, max(1, 6 - round((teams[home - 1]["strength"])))),
            })

    # Blank GW8 for four clubs, and hand two of them a double in GW10.
    blanked = {2, 5, 9, 14}
    fixtures = [f for f in fixtures if not (f["event"] == 8 and (f["team_h"] in blanked or f["team_a"] in blanked))]
    fixture_id += 1
    fixtures.append({
        "id": fixture_id, "event": 10, "team_h": 2, "team_a": 5, "finished": False,
        "kickoff_time": "2026-10-24T14:00:00Z", "team_h_difficulty": 3, "team_a_difficulty": 3,
    })
    fixture_id += 1
    fixtures.append({
        "id": fixture_id, "event": 10, "team_h": 9, "team_a": 14, "finished": False,
        "kickoff_time": "2026-10-25T14:00:00Z", "team_h_difficulty": 3, "team_a_difficulty": 3,
    })

    bootstrap = {"teams": teams, "elements": elements, "events": events,
                 "element_types": [{"id": i} for i in range(1, 5)]}

    # Build a legal fifteen for the demo manager.
    picks = _demo_picks(elements, rng)
    entry = {
        "id": 1234567, "name": "Demo XI", "player_first_name": "Demo", "player_last_name": "Manager",
        "summary_overall_rank": 412_886, "summary_overall_points": 142,
        "last_deadline_bank": 8, "last_deadline_value": 1006,
    }
    history = {"chips": [], "current": []}
    picks_payload = {
        "picks": picks,
        "entry_history": {"bank": 8, "value": 1006, "event_transfers": 1},
        "transfers": {"limit": 2},
    }
    return bootstrap, fixtures, entry, history, picks_payload


def _demo_picks(elements: list[dict], rng: random.Random) -> list[dict]:
    """Assemble a legal 15 within budget and the three-per-club limit."""
    shape = {1: 2, 2: 5, 3: 5, 4: 3}
    chosen: list[dict] = []
    club_counts: dict[int, int] = {}

    for position, needed in shape.items():
        pool = [
            e for e in elements
            if e["element_type"] == position and e["status"] == "a" and e["minutes"] > 150
        ]
        pool.sort(key=lambda e: e["now_cost"], reverse=True)
        taken = 0
        for element in pool:
            if taken >= needed:
                break
            if club_counts.get(element["team"], 0) >= 3:
                continue
            chosen.append(element)
            club_counts[element["team"]] = club_counts.get(element["team"], 0) + 1
            taken += 1

    picks = []
    for index, element in enumerate(chosen, start=1):
        picks.append({
            "element": element["id"], "position": index,
            "is_captain": index == 1, "is_vice_captain": index == 2,
            "selling_price": element["now_cost"], "purchase_price": element["now_cost"],
            "multiplier": 1 if index <= 11 else 0,
        })
    return picks


class SampleClient:
    """Stands in for FplClient, serving the generated season from memory."""

    def __init__(self, seed: int = 7) -> None:
        (
            self._bootstrap,
            self._fixtures,
            self._entry,
            self._history,
            self._picks,
        ) = build(seed)

    def bootstrap(self) -> dict:
        return self._bootstrap

    def fixtures(self) -> list[dict]:
        return self._fixtures

    def entry(self, entry_id: int) -> dict:
        return self._entry

    def entry_history(self, entry_id: int) -> dict:
        return self._history

    def picks(self, entry_id: int, gameweek: int) -> dict:
        return self._picks

    def transfers(self, entry_id: int) -> list:
        return []

    def element_summary(self, element_id: int) -> dict:
        """Per-match history consistent with the season totals."""
        element = next((e for e in self._bootstrap["elements"] if e["id"] == element_id), None)
        if element is None:
            return {"history": [], "fixtures": []}
        matches = max(1, round(element["minutes"] / 90))
        history = []
        for round_number in range(1, matches + 1):
            history.append({
                "round": round_number,
                "minutes": min(90, element["minutes"]),
                "clearances_blocks_interceptions": round(element["clearances_blocks_interceptions"] / matches),
                "tackles": round(element["tackles"] / matches),
                "recoveries": round(element["recoveries"] / matches),
            })
        return {"history": history, "fixtures": []}
