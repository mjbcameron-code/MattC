"""
Youth Academy management.

DoF responsibilities: maintain academy quality, promote graduates,
release those who won't make it, generate annual intakes.
"""
import random
from .models import db, Player
from .season import add_news

_FIRST = [
    'Danny', 'Jamie', 'Kyle', 'Tom', 'Jack', 'Ryan', 'Liam', 'Ben',
    'Adam', 'Luke', 'Harry', 'Jordan', 'Sam', 'Callum', 'Aaron',
    'Marcus', 'Leon', 'Tyler', 'George', 'Jay', 'Dean', 'Ross',
    'Charlie', 'Nathan', 'Connor', 'Kieran', 'Reece', 'Bobby', 'Ollie',
    'Shaun', 'Glen', 'Robbie', 'Terry', 'Lee', 'Brett', 'Craig',
]
_LAST = [
    'Smith', 'Jones', 'Wilson', 'Taylor', 'Brown', 'Davies', 'Evans',
    'Thomas', 'Roberts', 'Hughes', 'Morgan', 'Clarke', 'Walker',
    'Cooper', 'Ward', 'Morris', 'Richards', 'Hall', 'Green', 'Shaw',
    'Burton', 'Fletcher', 'Dixon', 'Wilkins', 'Cole', 'Mills', 'Frost',
    'Hammond', 'Pearce', 'Sharpe', 'Crossley', 'Barton', 'Neville',
]

POSITIONS = ['GK', 'RB', 'CB', 'LB', 'CM', 'AM', 'RM', 'LM', 'ST']

ACADEMY_LABELS = {1: 'Poor', 2: 'Basic', 3: 'Average', 4: 'Good', 5: 'Excellent'}
ACADEMY_UPGRADE_COST = {1: 1_000_000, 2: 2_000_000, 3: 4_000_000, 4: 8_000_000}


def get_youth_squad(gs):
    return (Player.query
            .filter_by(club_id=gs.managed_club_id, is_youth=True)
            .order_by(Player.position, Player.age.desc())
            .all())


def generate_intake(gs):
    """Annual youth intake. Call at season start."""
    aq = gs.managed_club.academy_quality or 2
    rng = random.Random(gs.current_season_id * 37 + gs.managed_club_id * 13)
    count = rng.randint(3 + aq, 5 + aq)
    players = []
    for _ in range(count):
        p = _make_youth_player(gs.managed_club, aq, rng)
        db.session.add(p)
        players.append(p)
    db.session.flush()
    names = ', '.join(p.name for p in players[:3])
    suffix = f' and {len(players) - 3} others' if len(players) > 3 else ''
    add_news(gs,
             f"Youth intake: {count} youngsters join the academy.",
             f"{names}{suffix} have joined {gs.managed_club.name}'s youth academy "
             f"as part of this season's intake.",
             'academy')
    return players


def seed_youth_for_new_game(gs):
    """Seed a small initial youth squad for the managed club on game start."""
    aq = gs.managed_club.academy_quality or 2
    rng = random.Random(gs.managed_club_id * 99 + 7)
    for _ in range(4 + aq):
        p = _make_youth_player(gs.managed_club, aq, rng)
        db.session.add(p)
    db.session.flush()


def _make_youth_player(club, aq, rng=None):
    if rng is None:
        rng = random
    age = rng.randint(15, 17)
    position = rng.choice(POSITIONS)
    ca = rng.randint(8, 16 + aq * 2)
    pa_ceiling = min(100, 25 + aq * 13)
    pa = rng.randint(min(ca + 12, pa_ceiling), max(ca + 15, pa_ceiling))
    name = f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"

    def a(frac):
        v = int(ca * frac / 10) + rng.randint(-2, 2)
        return max(1, min(20, v))

    if position == 'GK':
        attrs = dict(
            pace=a(4), acceleration=a(4), stamina=a(6), strength=a(5),
            agility=a(6), jumping=a(5), crossing=a(2), dribbling=a(2),
            finishing=a(1), first_touch=a(3), heading=a(4), long_shots=a(2),
            marking=a(3), passing=a(4), tackling=a(3), technique=a(3),
            aggression=a(5), anticipation=a(6), bravery=a(7), composure=a(6),
            concentration=a(7), creativity=a(3), decisions=a(6), determination=a(6),
            flair=a(2), off_the_ball=a(3), positioning=a(7), teamwork=a(6),
            work_rate=a(5), handling=a(7), reflexes=a(7), aerial=a(5),
            one_on_ones=a(6), rushing_out=a(5),
        )
    elif position in ('CB', 'RB', 'LB'):
        attrs = dict(
            pace=a(6), acceleration=a(6), stamina=a(7), strength=a(7),
            agility=a(5), jumping=a(6), crossing=a(4), dribbling=a(3),
            finishing=a(2), first_touch=a(5), heading=a(7), long_shots=a(3),
            marking=a(8), passing=a(5), tackling=a(8), technique=a(4),
            aggression=a(7), anticipation=a(6), bravery=a(7), composure=a(5),
            concentration=a(7), creativity=a(3), decisions=a(6), determination=a(7),
            flair=a(2), off_the_ball=a(4), positioning=a(7), teamwork=a(6),
            work_rate=a(7), handling=a(2), reflexes=a(2), aerial=a(4),
            one_on_ones=a(2), rushing_out=a(2),
        )
    elif position in ('CM', 'AM', 'RM', 'LM'):
        attrs = dict(
            pace=a(6), acceleration=a(6), stamina=a(8), strength=a(5),
            agility=a(6), jumping=a(5), crossing=a(6), dribbling=a(6),
            finishing=a(4), first_touch=a(7), heading=a(4), long_shots=a(5),
            marking=a(4), passing=a(7), tackling=a(5), technique=a(7),
            aggression=a(5), anticipation=a(6), bravery=a(5), composure=a(6),
            concentration=a(6), creativity=a(7), decisions=a(6), determination=a(6),
            flair=a(6), off_the_ball=a(6), positioning=a(5), teamwork=a(6),
            work_rate=a(7), handling=a(2), reflexes=a(2), aerial=a(3),
            one_on_ones=a(2), rushing_out=a(2),
        )
    else:  # ST
        attrs = dict(
            pace=a(7), acceleration=a(7), stamina=a(7), strength=a(6),
            agility=a(6), jumping=a(6), crossing=a(3), dribbling=a(6),
            finishing=a(7), first_touch=a(6), heading=a(6), long_shots=a(5),
            marking=a(2), passing=a(5), tackling=a(2), technique=a(6),
            aggression=a(5), anticipation=a(7), bravery=a(6), composure=a(6),
            concentration=a(5), creativity=a(5), decisions=a(6), determination=a(6),
            flair=a(6), off_the_ball=a(7), positioning=a(6), teamwork=a(5),
            work_rate=a(7), handling=a(2), reflexes=a(2), aerial=a(5),
            one_on_ones=a(6), rushing_out=a(2),
        )

    return Player(
        name=name,
        nationality='England',
        age=age,
        position=position,
        positions=position,
        club_id=club.id,
        is_youth=True,
        wage=rng.randint(100, 400),
        value=ca * 4000,
        contract_end=2003 + rng.randint(0, 2),
        current_ability=ca,
        potential_ability=pa,
        morale=70,
        **attrs,
    )


def promote_to_first_team(gs, player_id):
    p = Player.query.get(player_id)
    if not p or p.club_id != gs.managed_club_id or not p.is_youth:
        return False, "Player not found in youth squad."
    p.is_youth = False
    used = {pl.squad_number for pl in gs.managed_club.players if pl.squad_number}
    for n in range(1, 60):
        if n not in used:
            p.squad_number = n
            break
    p.wage = max(p.wage, 1000)  # minimum pro wage
    p.contract_end = max(p.contract_end, gs.current_season.year + 2)
    db.session.commit()
    add_news(gs,
             f"{p.name} promoted to first team.",
             f"{p.name} (age {p.age}) has graduated from the youth academy and "
             f"joins the first-team squad.", 'academy')
    return True, f"{p.name} promoted to the first team."


def release_youth(gs, player_id):
    p = Player.query.get(player_id)
    if not p or p.club_id != gs.managed_club_id or not p.is_youth:
        return False, "Player not found."
    name, age = p.name, p.age
    p.club_id = None
    db.session.commit()
    return True, f"{name} (age {age}) has been released from the academy."


def upgrade_academy(gs):
    club = gs.managed_club
    aq = club.academy_quality or 2
    if aq >= 5:
        return False, "Academy is already at maximum quality."
    cost = ACADEMY_UPGRADE_COST.get(aq, 0)
    if club.budget < cost:
        return False, f"Insufficient funds. Upgrade costs £{cost:,}."
    club.budget -= cost
    club.academy_quality = aq + 1
    db.session.commit()
    label = ACADEMY_LABELS[aq + 1]
    add_news(gs,
             f"Academy upgraded to {label} standard.",
             f"{club.name} have invested in their youth academy, raising it to "
             f"{label} standard. Expect better players in future intakes.", 'academy')
    return True, f"Academy upgraded to {label} standard."


def age_youth_players(gs):
    """Season-end: age youth squad, slight CA gain, release those past 18 with no deal."""
    new_year = gs.current_season.year + 1
    released = []
    for p in get_youth_squad(gs):
        p.age += 1
        if p.current_ability < p.potential_ability:
            gain = random.randint(0, 2)
            p.current_ability = min(p.potential_ability, p.current_ability + gain)
        if p.age >= 19 and p.contract_end <= new_year:
            p.club_id = None
            released.append(p.name)
    if released:
        add_news(gs,
                 f"{len(released)} youth player(s) released at contract end.",
                 f"The following academy players have left upon contract expiry: "
                 f"{', '.join(released)}.", 'academy')


def _backfill_academy_quality_club(club):
    """Ensure a single club has academy_quality set."""
    if not club.academy_quality:
        rep = club.reputation or 50
        club.academy_quality = (4 if rep >= 80 else 3 if rep >= 65
                                 else 2 if rep >= 45 else 1)


def get_coach_youth_recommendation(gs, player):
    """Simple heuristic: what does the head coach think of this youth player?"""
    mgr = gs.managed_club.head_coach
    if not mgr:
        return 'neutral'
    if player.potential_ability >= 70:
        return 'promote'
    if player.age >= 18 and player.current_ability >= 35:
        return 'promote'
    if player.age >= 19:
        return 'release'
    return 'neutral'
