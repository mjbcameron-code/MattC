"""
Database seeding and new-game initialisation.

Turns the compact `data/squads.py` definitions into full DB rows using the
attribute factory, then wires up leagues, fixtures, standings, and managers.
"""
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .models import db, League, Club, Player, Season, GameState, Manager
from data.player_factory import build_player


def database_is_seeded():
    return Club.query.first() is not None


def backfill_player_agents():
    """Assign agent names and aggression to any players that don't have one yet."""
    import random
    from game.contracts import gen_agent_name, gen_agent_aggression
    players = Player.query.filter(
        (Player.agent_name == None) | (Player.agent_name == '')
    ).all()
    for p in players:
        p.agent_name = gen_agent_name(p.id * 31 + 7)
        p.agent_aggression = gen_agent_aggression(p.current_ability)
        # 20% chance of release clause at 150-200% of estimated value
        if random.random() < 0.20:
            base_value = p.current_ability * 100000
            p.release_clause = int(base_value * random.uniform(1.5, 2.0))
    db.session.commit()


def seed_database():
    """Populate leagues, clubs, players and managers. Runs once on empty DB."""
    if database_is_seeded():
        # Backfill managers if this is an existing DB that pre-dates the Manager model
        if Manager.query.count() == 0:
            seed_managers()
        # Backfill agent data for existing saves
        if Player.query.filter((Player.agent_name == None) | (Player.agent_name == '')).first():
            backfill_player_agents()
        # Backfill scout pool for existing saves
        from .models import Scout
        from game.scouting import seed_scouts
        if Scout.query.count() == 0:
            seed_scouts()
        # Backfill stadiums for existing saves
        from .models import Stadium
        if Stadium.query.count() == 0:
            _seed_stadiums_and_training()
        return

    from data.squads import CLUBS as PL_CLUBS
    try:
        from data.european_squads import CLUBS as EU_CLUBS
    except ImportError:
        EU_CLUBS = []
    CLUBS = PL_CLUBS + EU_CLUBS

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
    seed_managers()
    backfill_player_agents()
    from game.scouting import seed_scouts
    seed_scouts()
    _seed_stadiums_and_training()


def _seed_stadiums_and_training():
    """Create stadiums and set training levels for all clubs."""
    import random
    from .models import Club, Stadium
    for club in Club.query.all():
        if not club.stadium:
            rep = club.reputation or 50
            if rep >= 80:
                cap, qual = random.randint(40000, 65000), 8
            elif rep >= 65:
                cap, qual = random.randint(25000, 40000), 6
            elif rep >= 50:
                cap, qual = random.randint(18000, 28000), 5
            elif rep >= 35:
                cap, qual = random.randint(10000, 20000), 4
            else:
                cap, qual = random.randint(5000, 12000), 3
            db.session.add(Stadium(club_id=club.id, capacity=cap, quality=qual,
                                   name=f"{club.short_name} Ground"))
        if not club.training_level:
            rep = club.reputation or 50
            club.training_level = (4 if rep >= 80 else 3 if rep >= 65
                                   else 2 if rep >= 45 else 1)
    db.session.commit()


def seed_managers():
    """Create the manager pool and assign the best to PL clubs by reputation."""
    from data.managers import MANAGERS as MANAGER_DATA

    Manager.query.delete()
    db.session.flush()

    mgr_objects = []
    for m in MANAGER_DATA:
        name, nat, age, rep, tac, mm, det, fmt, style, wage = m
        mgr = Manager(
            name=name, nationality=nat, age=age, reputation=rep,
            tactical_ability=tac, man_management=mm, determination=det,
            preferred_formation=fmt, preferred_style=style,
            wage=wage, contract_end=2004, satisfaction=70,
        )
        db.session.add(mgr)
        mgr_objects.append(mgr)
    db.session.flush()

    # Assign top-reputation managers to PL clubs, matched by club reputation
    pl_league = League.query.filter_by(name='Premier League').first()
    if pl_league:
        pl_clubs = sorted(
            Club.query.filter_by(league_id=pl_league.id).all(),
            key=lambda c: c.reputation, reverse=True,
        )
        sorted_mgrs = sorted(mgr_objects, key=lambda m: m.reputation, reverse=True)
        for i, club in enumerate(pl_clubs):
            if i < len(sorted_mgrs):
                sorted_mgrs[i].club_id = club.id

    db.session.commit()


def new_game(manager_name, club_id):
    """Create a fresh GameState for a Director of Football career."""
    from .season import generate_fixtures, init_standings, add_news
    from game.cups import generate_fa_cup, generate_league_cup

    # Wipe season-specific data
    GameState.query.delete()
    Season.query.delete()
    from .models import Match, Standing, PlayerStat, Lineup, NewsItem, MatchEvent, Loan, OwnerDemand
    from .models import ContractNegotiation, TransferBid
    MatchEvent.query.delete()
    Match.query.delete()
    Standing.query.delete()
    PlayerStat.query.delete()
    Lineup.query.delete()
    NewsItem.query.delete()
    Loan.query.delete()
    OwnerDemand.query.delete()
    ContractNegotiation.query.delete()
    TransferBid.query.delete()
    from .models import Scout, ScoutKnowledge, SponsorDeal
    SponsorDeal.query.delete()
    from .models import Scout, ScoutKnowledge
    ScoutKnowledge.query.delete()
    for sc in Scout.query.all():
        sc.club_id = None
        sc.assignment_player_id = None
        sc.assignment_region = None
    db.session.commit()

    # Reset manager and scout pools for a clean career start
    seed_managers()
    from game.scouting import seed_scouts, assign_starting_scouts
    seed_scouts()

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

    # Determine initial formation from club's assigned manager
    club = Club.query.get(club_id)
    club_mgr = Manager.query.filter_by(club_id=club_id).first()
    initial_formation = club_mgr.preferred_formation if club_mgr else '4-4-2'
    initial_tactic = _style_to_tactic(club_mgr.preferred_style) if club_mgr else 'Normal'

    gs = GameState(
        managed_club_id=club_id,
        current_date='2001-08-18',
        current_season_id=season.id,
        manager_name=manager_name,
        formation=initial_formation,
        tactic=initial_tactic,
        created_at=datetime.utcnow().isoformat(),
    )
    db.session.add(gs)
    db.session.commit()

    add_news(gs, f"Welcome to {club.name}, {manager_name}!",
             f"The board have appointed {manager_name} as Director of Football at "
             f"{club.name}. Your responsibilities include recruiting the manager, "
             f"managing the transfer budget (£{club.budget:,}), keeping the board "
             f"confident, and ensuring the club's long-term success. Good luck!",
             category='general')

    if club_mgr:
        add_news(gs, f"{club_mgr.name} continues as Head Coach",
                 f"{club_mgr.name} remains in charge on the pitch. Work with him "
                 f"in the transfer market to build the squad he needs.",
                 category='staff')

    from game.board import set_board_target
    set_board_target(gs)

    from game.staff import generate_manager_request
    generate_manager_request(gs)

    assign_starting_scouts(club_id, 2)

    auto_pick_lineup(gs)
    return gs


def auto_pick_lineup(game_state, formation=None):
    """Select a starting XI + subs for the managed club.
    Formation comes from the head coach's preference if not specified."""
    from .models import Lineup, Player

    if formation is None:
        mgr = game_state.managed_club.head_coach
        formation = (mgr.preferred_formation if mgr else None) or game_state.formation

    Lineup.query.filter_by(game_state_id=game_state.id).delete()

    FORMATIONS = {
        '4-4-2':   ['GK', 'RB', 'CB', 'CB', 'LB', 'RM', 'CM', 'CM', 'LM', 'ST', 'ST'],
        '4-3-3':   ['GK', 'RB', 'CB', 'CB', 'LB', 'CM', 'CM', 'CM', 'RM', 'ST', 'LM'],
        '4-5-1':   ['GK', 'RB', 'CB', 'CB', 'LB', 'RM', 'CM', 'CM', 'AM', 'LM', 'ST'],
        '3-5-2':   ['GK', 'CB', 'CB', 'CB', 'RM', 'CM', 'CM', 'AM', 'LM', 'ST', 'ST'],
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

    remaining = sorted([p for p in players if p.id not in used],
                       key=lambda p: p.current_ability, reverse=True)[:5]
    for p in remaining:
        lu = Lineup(game_state_id=game_state.id, player_id=p.id,
                    slot=slot, position_played=p.position)
        db.session.add(lu)
        slot += 1

    db.session.commit()


def _style_to_tactic(style):
    return {'attacking': 'Attack', 'defensive': 'Defend', 'balanced': 'Normal'}.get(
        style, 'Normal')
