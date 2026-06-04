"""
Youth Academy management.

DoF responsibilities: maintain academy quality, promote graduates,
release those who won't make it, generate annual intakes.
"""
import random
from .models import db, Player
from .season import add_news
from data.player_factory import build_player

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
    base_year = gs.current_season.year if gs.current_season else 2025
    count = rng.randint(3 + aq, 5 + aq)
    players = []
    for _ in range(count):
        p = _make_youth_player(gs.managed_club, aq, rng, base_year)
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
    base_year = gs.current_season.year if gs.current_season else 2025
    for _ in range(4 + aq):
        p = _make_youth_player(gs.managed_club, aq, rng, base_year)
        db.session.add(p)
    db.session.flush()


# Distinct surnames per intake so two youths rarely share a build seed
_youth_seq = 0


def _make_youth_player(club, aq, rng=None, base_year=2025):
    """Generate a teenager on the same 1-200 ability scale as the senior squad.

    Current ability is deliberately low (a 15-17 year old is nowhere near the
    first team yet); the interest is in *potential*. A stronger academy raises
    both the odds and the ceiling of a genuine prospect emerging.
    """
    global _youth_seq
    if rng is None:
        rng = random
    age = rng.randint(15, 17)
    position = rng.choice(POSITIONS)

    # Current quality: low for a teenager (2-6 on the 1-20 scale → CA 20-60)
    q_cur = rng.randint(2, 6)

    # Potential quality distribution, lifted by academy quality
    roll = rng.random()
    if roll < 0.55:
        q_pot = rng.randint(6, 9)       # squad filler / lower-league level
    elif roll < 0.88:
        q_pot = rng.randint(9, 12)      # solid first-team potential
    else:
        q_pot = rng.randint(12, 16)     # genuine prospect
    q_pot = min(20, q_pot + (aq - 1))
    q_pot = max(q_pot, q_cur + 2)

    _youth_seq += 1
    name = f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"
    # Unique seed name so build_player's deterministic RNG varies per intake
    built = build_player(f"{name} #{_youth_seq}", 'England', age, position,
                         q_cur, q_pot)

    return Player(
        name=name,
        nationality='England',
        age=age,
        position=position,
        positions=position,
        club_id=club.id,
        is_youth=True,
        wage=rng.randint(100, 400),
        value=built['value'],
        contract_end=base_year + rng.randint(2, 4),
        current_ability=built['current_ability'],
        potential_ability=built['potential_ability'],
        morale=70,
        **built['attrs'],
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
    """Season-end: age youth squad, develop toward potential, release the rest."""
    new_year = gs.current_season.year + 1
    tl = gs.managed_club.training_level or 2
    released = []
    for p in get_youth_squad(gs):
        p.age += 1
        if p.current_ability < p.potential_ability:
            gap = p.potential_ability - p.current_ability
            # Better training facilities accelerate development
            gain = random.randint(2, 6) + tl
            p.current_ability = min(p.potential_ability,
                                    p.current_ability + min(gain, gap))
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
    # Scale is 1-200; 120 ≈ 3★ ceiling, 90 ≈ 2.25★
    if player.potential_ability >= 120:
        return 'promote'
    if player.age >= 18 and player.current_ability >= 80:
        return 'promote'
    if player.age >= 19 and player.potential_ability < 90:
        return 'release'
    return 'neutral'
