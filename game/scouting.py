"""
Scouting network for the Director of Football.

The DoF hires scouts and assigns them to assess individual transfer targets
or to scour a region for talent. Players the club has not scouted reveal only
limited information; a completed report unlocks an ability/potential estimate
and a recommendation. Better scouts (higher judging) give tighter estimates.
"""
import random
from .models import db, Scout, ScoutKnowledge, Player, Club
from .season import add_news

REGIONS = ['England', 'Europe', 'South America', 'World']

# Map nationalities to scouting regions for region assignments
_EUROPE = {'French','German','Italian','Spanish','Portuguese','Dutch','Swedish',
           'Czech','Russian','Belgian','Danish','Norwegian','Polish','Scottish',
           'Welsh','Irish','Greek','Croatian','Serbian','Swiss','Austrian','Turkish'}
_SOUTH_AM = {'Argentine','Brazilian','Uruguayan','Chilean','Colombian','Paraguayan',
             'Peruvian','Mexican','Ecuadorian','Bolivian'}


def region_of(nationality):
    if nationality == 'English':
        return 'England'
    if nationality in _SOUTH_AM:
        return 'South America'
    if nationality in _EUROPE:
        return 'Europe'
    return 'World'


def scout_covers(scout, nationality):
    return scout.region == 'World' or scout.region == region_of(nationality)


# --- seeding -------------------------------------------------------------

def seed_scouts():
    """Recreate the scout pool as free agents."""
    from data.scouts import SCOUTS
    Scout.query.delete()
    db.session.flush()
    for name, nat, age, ja, jp, region, wage in SCOUTS:
        db.session.add(Scout(name=name, nationality=nat, age=age,
                             judging_ability=ja, judging_potential=jp,
                             region=region, wage=wage))
    db.session.commit()


def assign_starting_scouts(club_id, count=2):
    """Give a club its initial scouts (best 2 mid-tier free agents)."""
    free = (Scout.query.filter_by(club_id=None)
            .order_by(Scout.judging_ability.desc()).all())
    # pick a couple of solid-but-not-elite scouts to start
    picks = free[3:3 + count] if len(free) > 3 + count else free[:count]
    for s in picks:
        s.club_id = club_id
    db.session.commit()


# --- queries -------------------------------------------------------------

def get_club_scouts(game_state):
    return Scout.query.filter_by(club_id=game_state.managed_club_id).all()

def get_available_scouts():
    return (Scout.query.filter_by(club_id=None)
            .order_by(Scout.judging_ability.desc()).all())

def get_idle_club_scouts(game_state):
    return Scout.query.filter_by(
        club_id=game_state.managed_club_id,
        assignment_player_id=None, assignment_region=None).all()

def get_knowledge(game_state, player_id):
    return ScoutKnowledge.query.filter_by(
        game_state_id=game_state.id, player_id=player_id).first()

def get_or_create_knowledge(game_state, player_id):
    k = get_knowledge(game_state, player_id)
    if not k:
        k = ScoutKnowledge(game_state_id=game_state.id, player_id=player_id,
                           knowledge=0)
        db.session.add(k)
        db.session.flush()
    return k

def get_shortlist(game_state):
    return (ScoutKnowledge.query
            .filter_by(game_state_id=game_state.id)
            .filter((ScoutKnowledge.shortlisted == True) | (ScoutKnowledge.knowledge > 0))
            .order_by(ScoutKnowledge.knowledge.desc())
            .all())


# --- scout employment ----------------------------------------------------

def hire_scout(game_state, scout_id):
    s = Scout.query.get(scout_id)
    if not s:
        return False, "Scout not found."
    if s.club_id is not None:
        return False, "That scout is already employed."
    s.club_id = game_state.managed_club_id
    db.session.commit()
    add_news(game_state, f"{s.name} joins the scouting team",
             f"{s.name}, a {s.region} specialist (judging {s.judging_ability}/20), "
             f"has joined {game_state.managed_club.name}'s recruitment team on "
             f"£{s.wage:,}/wk.", 'scouting')
    return True, f"{s.name} hired."

def fire_scout(game_state, scout_id):
    s = Scout.query.get(scout_id)
    if not s or s.club_id != game_state.managed_club_id:
        return False, "Scout not on your staff."
    s.club_id = None
    s.assignment_player_id = None
    s.assignment_region = None
    db.session.commit()
    return True, f"{s.name} released."


# --- assignments ---------------------------------------------------------

def assign_scout_to_player(game_state, scout_id, player_id):
    s = Scout.query.get(scout_id)
    if not s or s.club_id != game_state.managed_club_id:
        return False, "Scout not on your staff."
    player = Player.query.get(player_id)
    if not player:
        return False, "Player not found."
    if player.club_id == game_state.managed_club_id:
        return False, "You already know your own players fully."
    s.assignment_player_id = player_id
    s.assignment_region = None
    get_or_create_knowledge(game_state, player_id)
    db.session.commit()
    return True, f"{s.name} is now scouting {player.name}."

def assign_scout_to_region(game_state, scout_id, region):
    s = Scout.query.get(scout_id)
    if not s or s.club_id != game_state.managed_club_id:
        return False, "Scout not on your staff."
    if region not in REGIONS:
        return False, "Unknown region."
    s.assignment_region = region
    s.assignment_player_id = None
    db.session.commit()
    return True, f"{s.name} is now scouting the {region} region."

def unassign_scout(game_state, scout_id):
    s = Scout.query.get(scout_id)
    if not s or s.club_id != game_state.managed_club_id:
        return False, "Scout not on your staff."
    s.assignment_player_id = None
    s.assignment_region = None
    db.session.commit()
    return True, f"{s.name} recalled."

def toggle_shortlist(game_state, player_id):
    k = get_or_create_knowledge(game_state, player_id)
    k.shortlisted = not k.shortlisted
    db.session.commit()
    return True, ("Added to shortlist." if k.shortlisted else "Removed from shortlist.")


# --- per-advance processing ---------------------------------------------

def process_scouting(game_state):
    """Advance all active scouting assignments. Called once per match day."""
    scouts = get_club_scouts(game_state)
    for s in scouts:
        if s.assignment_player_id:
            _progress_player(game_state, s)
        elif s.assignment_region:
            _scour_region(game_state, s)
    db.session.commit()


def _progress_player(game_state, scout):
    k = get_or_create_knowledge(game_state, scout.assignment_player_id)
    if k.complete:
        scout.assignment_player_id = None
        return
    gain = 6 + scout.judging_ability // 3
    k.knowledge = min(100, k.knowledge + gain)
    if k.knowledge >= 100 and not k.complete:
        _finalise_report(game_state, scout, k)
        scout.assignment_player_id = None


def _scour_region(game_state, scout):
    if random.random() > 0.15:
        return
    # candidate players in scout's region, not at managed club, not already known
    known_ids = [r.player_id for r in ScoutKnowledge.query.filter_by(
        game_state_id=game_state.id).all()]
    pool = (Player.query
            .filter(Player.club_id != game_state.managed_club_id)
            .filter(~Player.id.in_(known_ids) if known_ids else True)
            .all())
    pool = [p for p in pool if scout_covers(scout, p.nationality)]
    if not pool:
        return
    # bias toward higher potential
    pool.sort(key=lambda p: p.potential_ability or 0, reverse=True)
    pick = random.choice(pool[:25] or pool)
    k = get_or_create_knowledge(game_state, pick.id)
    k.knowledge = max(k.knowledge, random.randint(25, 35))
    k.shortlisted = True
    db.session.flush()
    add_news(game_state, f"Scout report: {pick.name} flagged by {scout.name}",
             f"{scout.name} has identified {pick.name} ({pick.age}, "
             f"{pick.nationality}, {pick.position}) at "
             f"{pick.club.name if pick.club else 'a free agent'} as one to watch. "
             f"He has been added to your shortlist. Assign a scout to him for a "
             f"full report.", 'scouting')


def _finalise_report(game_state, scout, k):
    player = Player.query.get(k.player_id)
    if not player:
        return
    ca = player.current_ability or 100
    pa = player.potential_ability or ca
    ca_margin = max(2, (20 - scout.judging_ability) * 2 + random.randint(0, 4))
    pa_margin = max(3, (20 - scout.judging_potential) * 3 + random.randint(0, 6))
    k.ca_low, k.ca_high = max(0, ca - ca_margin), ca + ca_margin
    k.pa_low, k.pa_high = max(0, pa - pa_margin), pa + pa_margin
    k.complete = True
    k.shortlisted = True

    star = stars(ca)
    pot_star = stars(pa)
    if pot_star - star >= 1.5:
        verdict = (f"A real prospect. {player.name} has the potential to develop "
                   f"well beyond his current level — a smart long-term signing.")
    elif star >= 4:
        verdict = (f"An excellent player who would strengthen the squad immediately. "
                   f"Recommended if the finances work.")
    elif star >= 3:
        verdict = (f"A solid, dependable option. Worth considering as a squad player.")
    else:
        verdict = (f"Below the level we should be targeting. Not recommended.")
    k.recommendation = f"{scout.name}: {verdict}"
    db.session.flush()
    add_news(game_state, f"Scouting report complete: {player.name}",
             f"{scout.name} has filed a full report on {player.name}. "
             f"Estimated ability {star:.1f}★, potential {pot_star:.1f}★. "
             f"{verdict} See the player's profile or your shortlist.", 'scouting')


# --- display helpers (used by templates via route) -----------------------

def stars(ca):
    return max(0.5, min(5.0, round((ca or 0) / 40 * 2) / 2))

def knowledge_tier(k_value):
    if not k_value or k_value <= 0:
        return 0
    if k_value < 40:
        return 1
    if k_value < 100:
        return 2
    return 3
