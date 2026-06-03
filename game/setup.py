"""
Database seeding and new-game initialisation.

Turns the compact `data/squads.py` definitions into full DB rows using the
attribute factory, then wires up leagues, fixtures and standings.
"""
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .models import db, League, Club, Player, Season, GameState
from data.player_factory import build_player


def database_is_seeded():
    return Club.query.first() is not None


def seed_database():
    """Populate leagues, clubs and players from squad data. Idempotent-ish:
    only runs if the DB is empty."""
    if database_is_seeded():
        return

    from data.squads import CLUBS as PL_CLUBS
    try:
        from data.european_squads import CLUBS as EU_CLUBS
    except ImportError:
        EU_CLUBS = []
    CLUBS = PL_CLUBS + EU_CLUBS

    # Create leagues (collect unique league names)
    league_objs = {}
    LEAGUE_COUNTRIES = {
        'Premier League': 'England',
        'La Liga': 'Spain',
        'Serie A': 'Italy',
        'Bundesliga': 'Germany',
        'Ligue 1': 'France',
    }
    for club_def in CLUBS:
        lname = club_def['league']
        if lname not in league_objs:
            country = LEAGUE_COUNTRIES.get(lname, 'Unknown')
            lg = League(name=lname, country=country, level=1)
            db.session.add(lg)
            league_objs[lname] = lg
    db.session.flush()

    squad_number_counter = {}
    seen_player_names = set()
    for club_def in CLUBS:
        club = Club(
            name=club_def['name'],
            short_name=club_def.get('short_name', club_def['name']),
            league_id=league_objs[club_def['league']].id,
            reputation=club_def.get('reputation', 50),
            budget=club_def.get('budget', 5000000),
            wage_budget=club_def.get('wage_budget', 500000),
            primary_color=club_def.get('primary_color', '#cc0000'),
            secondary_color=club_def.get('secondary_color', '#ffffff'),
        )
        db.session.add(club)
        db.session.flush()

        squad_number_counter[club.id] = 1
        for pdef in club_def['players']:
            name, nationality, age, position, quality, potential = pdef
            # Skip duplicate player names (a few players appear at two clubs in the
            # source data, e.g. mid-season movers); keep the first occurrence.
            if name in seen_player_names:
                continue
            seen_player_names.add(name)
            built = build_player(name, nationality, age, position, quality, potential)
            attrs = built['attrs']
            player = Player(
                name=built['name'],
                nationality=built['nationality'],
                age=built['age'],
                position=built['position'],
                positions=built['positions'],
                club_id=club.id,
                wage=built['wage'],
                value=built['value'],
                contract_end=2004,
                squad_number=squad_number_counter[club.id],
                current_ability=built['current_ability'],
                potential_ability=built['potential_ability'],
                morale=70,
                condition=100,
                **attrs,
            )
            db.session.add(player)
            squad_number_counter[club.id] += 1

    db.session.commit()


def new_game(manager_name, club_id):
    """Create a fresh GameState managing the given club, plus a season with
    fixtures and standings."""
    from .season import generate_fixtures, init_standings, add_news
    from game.cups import generate_fa_cup, generate_league_cup

    # Wipe any existing game state / season-specific data for a clean start
    GameState.query.delete()
    Season.query.delete()
    from .models import Match, Standing, PlayerStat, Lineup, NewsItem, MatchEvent, Loan
    MatchEvent.query.delete()
    Match.query.delete()
    Standing.query.delete()
    PlayerStat.query.delete()
    Lineup.query.delete()
    NewsItem.query.delete()
    Loan.query.delete()
    db.session.commit()

    season = Season(year=2001, name='2001/02')
    db.session.add(season)
    db.session.flush()

    leagues = League.query.all()
    for league in leagues:
        generate_fixtures(season, league)
        init_standings(season, league)

    generate_fa_cup(season)
    generate_league_cup(season)

    from game.europe import generate_champions_league, generate_uefa_cup
    generate_champions_league(season)
    generate_uefa_cup(season)

    gs = GameState(
        managed_club_id=club_id,
        current_date='2001-08-18',
        current_season_id=season.id,
        manager_name=manager_name,
        formation='4-4-2',
        tactic='Normal',
        created_at=datetime.utcnow().isoformat(),
    )
    db.session.add(gs)
    db.session.commit()

    club = Club.query.get(club_id)
    add_news(gs, f"Welcome to {club.name}, {manager_name}!",
             f"The board have appointed {manager_name} as the new manager of "
             f"{club.name}. The fans expect results this season. You have a "
             f"transfer budget of £{club.budget:,} to strengthen the squad. "
             f"Good luck!", category='general')

    # Set initial board target
    from game.board import set_board_target
    set_board_target(gs)

    # Auto-pick an initial lineup
    auto_pick_lineup(gs)
    return gs


def auto_pick_lineup(game_state, formation=None):
    """Select a starting XI + subs for the managed club based on formation."""
    from .models import Lineup, Player

    formation = formation or game_state.formation
    Lineup.query.filter_by(game_state_id=game_state.id).delete()

    # Formation -> required positions for slots 1-11
    FORMATIONS = {
        '4-4-2': ['GK', 'RB', 'CB', 'CB', 'LB', 'RM', 'CM', 'CM', 'LM', 'ST', 'ST'],
        '4-3-3': ['GK', 'RB', 'CB', 'CB', 'LB', 'CM', 'CM', 'CM', 'RM', 'ST', 'LM'],
        '4-5-1': ['GK', 'RB', 'CB', 'CB', 'LB', 'RM', 'CM', 'CM', 'AM', 'LM', 'ST'],
        '3-5-2': ['GK', 'CB', 'CB', 'CB', 'RM', 'CM', 'CM', 'AM', 'LM', 'ST', 'ST'],
        '4-4-1-1': ['GK', 'RB', 'CB', 'CB', 'LB', 'RM', 'CM', 'CM', 'LM', 'AM', 'ST'],
    }
    needed = FORMATIONS.get(formation, FORMATIONS['4-4-2'])

    from .injuries import is_suspended
    players = [p for p in Player.query.filter_by(
        club_id=game_state.managed_club_id, is_injured=False).all()
               if not is_suspended(p.id)]
    used = set()
    slot = 1

    def best_for(pos):
        # Find best available player who can play pos (exact, then related)
        related = {
            'GK': ['GK'],
            'RB': ['RB', 'CB', 'LB', 'RM'],
            'LB': ['LB', 'CB', 'RB', 'LM'],
            'CB': ['CB', 'RB', 'LB'],
            'RM': ['RM', 'LM', 'CM', 'AM'],
            'LM': ['LM', 'RM', 'CM', 'AM'],
            'CM': ['CM', 'AM', 'RM', 'LM'],
            'AM': ['AM', 'CM', 'RM', 'LM', 'ST'],
            'ST': ['ST', 'AM'],
        }
        for want in related.get(pos, [pos]):
            cands = sorted(
                [p for p in players if p.id not in used and
                 (p.position == want or want in p.get_positions_list())],
                key=lambda p: p.current_ability, reverse=True)
            if cands:
                return cands[0]
        # fallback: any unused player
        cands = sorted([p for p in players if p.id not in used],
                       key=lambda p: p.current_ability, reverse=True)
        return cands[0] if cands else None

    for pos in needed:
        p = best_for(pos)
        if p:
            used.add(p.id)
            lu = Lineup(game_state_id=game_state.id, player_id=p.id,
                        slot=slot, position_played=pos)
            db.session.add(lu)
            slot += 1

    # Subs: next 5 best available
    remaining = sorted([p for p in players if p.id not in used],
                       key=lambda p: p.current_ability, reverse=True)[:5]
    for p in remaining:
        lu = Lineup(game_state_id=game_state.id, player_id=p.id,
                    slot=slot, position_played=p.position)
        db.session.add(lu)
        slot += 1

    db.session.commit()
