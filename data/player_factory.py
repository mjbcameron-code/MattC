"""
Real 2001/02 squad data (best-effort) for the Championship Manager 01/02 clone.

Each player is defined as a compact tuple:
    (name, nationality, age, position, quality, potential)

- quality / potential are 1-20 "star-ish" ratings approximating real ability in
  the 2001/02 season. Full 30+ attribute sets are derived from these by
  `build_player()` using position profiles, so squads feel authentic without
  hand-tuning every slider.
- positions: GK, RB, CB, LB, RM, CM, LM, AM, ST

The Premier League 2001/02 is modelled in full (20 clubs). A handful of marquee
European clubs are included so the transfer market and reputation system have
texture.
"""

import random
import hashlib

# ---------------------------------------------------------------------------
# Attribute generation
# ---------------------------------------------------------------------------

POSITION_PROFILES = {
    # weight multipliers per attribute group (technical, mental, physical, gk)
    'GK': {
        'handling': 1.0, 'reflexes': 1.0, 'aerial': 0.9, 'one_on_ones': 0.95,
        'rushing_out': 0.85, 'positioning': 0.95, 'concentration': 0.9,
        'composure': 0.85, 'decisions': 0.85, 'anticipation': 0.85,
        'agility': 0.85, 'jumping': 0.8, 'strength': 0.7, 'bravery': 0.8,
        'kicking': 0.8, 'finishing': 0.1, 'pace': 0.4, 'dribbling': 0.2,
        'passing': 0.5, 'tackling': 0.2, 'heading': 0.3, 'marking': 0.2,
    },
    'CB': {
        'tackling': 1.0, 'marking': 1.0, 'heading': 0.95, 'positioning': 0.95,
        'strength': 0.95, 'jumping': 0.9, 'bravery': 0.9, 'concentration': 0.9,
        'composure': 0.8, 'decisions': 0.85, 'anticipation': 0.85, 'aggression': 0.8,
        'pace': 0.7, 'passing': 0.65, 'first_touch': 0.6, 'finishing': 0.35,
        'dribbling': 0.4, 'crossing': 0.4, 'work_rate': 0.8, 'determination': 0.85,
    },
    'RB': {
        'tackling': 0.9, 'marking': 0.85, 'positioning': 0.85, 'pace': 0.9,
        'stamina': 0.9, 'crossing': 0.85, 'work_rate': 0.9, 'teamwork': 0.85,
        'concentration': 0.8, 'decisions': 0.8, 'anticipation': 0.8,
        'first_touch': 0.7, 'passing': 0.75, 'dribbling': 0.65, 'heading': 0.7,
        'strength': 0.75, 'finishing': 0.4, 'determination': 0.8, 'acceleration': 0.85,
    },
    'LB': {
        'tackling': 0.9, 'marking': 0.85, 'positioning': 0.85, 'pace': 0.9,
        'stamina': 0.9, 'crossing': 0.85, 'work_rate': 0.9, 'teamwork': 0.85,
        'concentration': 0.8, 'decisions': 0.8, 'anticipation': 0.8,
        'first_touch': 0.7, 'passing': 0.75, 'dribbling': 0.65, 'heading': 0.7,
        'strength': 0.75, 'finishing': 0.4, 'determination': 0.8, 'acceleration': 0.85,
    },
    'CM': {
        'passing': 1.0, 'work_rate': 0.95, 'stamina': 0.95, 'teamwork': 0.9,
        'decisions': 0.9, 'creativity': 0.85, 'tackling': 0.8, 'technique': 0.85,
        'first_touch': 0.85, 'composure': 0.85, 'anticipation': 0.85,
        'positioning': 0.8, 'long_shots': 0.75, 'determination': 0.85,
        'off_the_ball': 0.8, 'strength': 0.7, 'finishing': 0.6, 'dribbling': 0.7,
        'flair': 0.7, 'concentration': 0.8,
    },
    'RM': {
        'crossing': 0.95, 'dribbling': 0.9, 'pace': 0.9, 'technique': 0.85,
        'creativity': 0.85, 'flair': 0.85, 'stamina': 0.9, 'work_rate': 0.85,
        'first_touch': 0.85, 'passing': 0.85, 'off_the_ball': 0.8,
        'acceleration': 0.9, 'finishing': 0.65, 'long_shots': 0.7, 'agility': 0.85,
        'teamwork': 0.8, 'decisions': 0.8,
    },
    'LM': {
        'crossing': 0.95, 'dribbling': 0.9, 'pace': 0.9, 'technique': 0.85,
        'creativity': 0.85, 'flair': 0.85, 'stamina': 0.9, 'work_rate': 0.85,
        'first_touch': 0.85, 'passing': 0.85, 'off_the_ball': 0.8,
        'acceleration': 0.9, 'finishing': 0.65, 'long_shots': 0.7, 'agility': 0.85,
        'teamwork': 0.8, 'decisions': 0.8,
    },
    'AM': {
        'creativity': 1.0, 'technique': 0.95, 'passing': 0.9, 'dribbling': 0.9,
        'flair': 0.9, 'first_touch': 0.95, 'composure': 0.85, 'off_the_ball': 0.85,
        'finishing': 0.8, 'long_shots': 0.8, 'decisions': 0.85, 'agility': 0.85,
        'anticipation': 0.8, 'acceleration': 0.8, 'pace': 0.78, 'work_rate': 0.7,
    },
    'ST': {
        'finishing': 1.0, 'off_the_ball': 0.95, 'composure': 0.9, 'pace': 0.9,
        'acceleration': 0.9, 'first_touch': 0.85, 'anticipation': 0.85,
        'heading': 0.8, 'dribbling': 0.8, 'technique': 0.8, 'strength': 0.78,
        'flair': 0.78, 'jumping': 0.75, 'long_shots': 0.7, 'bravery': 0.8,
        'determination': 0.85, 'agility': 0.8,
    },
}

ALL_ATTRS = [
    'acceleration', 'pace', 'stamina', 'strength', 'agility', 'jumping',
    'crossing', 'dribbling', 'finishing', 'first_touch', 'heading', 'long_shots',
    'marking', 'passing', 'tackling', 'technique', 'aggression', 'anticipation',
    'bravery', 'composure', 'concentration', 'creativity', 'decisions',
    'determination', 'flair', 'off_the_ball', 'positioning', 'teamwork',
    'work_rate', 'handling', 'reflexes', 'aerial', 'one_on_ones', 'rushing_out',
]


def _seeded_random(name):
    """Deterministic RNG seeded by player name for reproducible attributes."""
    h = int(hashlib.md5(name.encode('utf-8')).hexdigest(), 16)
    return random.Random(h)


def build_player(name, nationality, age, position, quality, potential):
    """Build a full attribute dict from a compact player definition."""
    rng = _seeded_random(name)
    profile = POSITION_PROFILES.get(position, POSITION_PROFILES['CM'])

    # Base attribute level: quality (1-20) maps to a centre point
    base = quality
    attrs = {}
    for attr in ALL_ATTRS:
        weight = profile.get(attr, 0.55)  # default for unlisted attrs
        # Higher weight -> attribute closer to (or above) base; lower weight -> lower
        centre = base * weight
        # Spread: better players are more consistent
        spread = max(1.5, 4.0 - quality / 8)
        val = centre + rng.uniform(-spread, spread)
        attrs[attr] = int(max(1, min(20, round(val))))

    # GK kicking maps onto passing for non-gk schema; ensure gk attrs sane
    if position == 'GK':
        for a in ('handling', 'reflexes', 'one_on_ones', 'aerial', 'rushing_out'):
            attrs[a] = int(max(1, min(20, round(base * profile.get(a, 0.9) +
                                              rng.uniform(-2, 2)))))
        for a in ('finishing', 'dribbling', 'tackling', 'marking', 'heading'):
            attrs[a] = int(max(1, min(8, attrs[a])))
    else:
        # outfield players have modest GK attrs
        for a in ('handling', 'reflexes', 'one_on_ones', 'aerial', 'rushing_out'):
            attrs[a] = rng.randint(1, 6)

    # Current/potential ability scaled 1-200 (CM-style)
    current_ability = int(quality * 10)
    potential_ability = int(max(quality, potential) * 10)

    return {
        'name': name,
        'nationality': nationality,
        'age': age,
        'position': position,
        'positions': position,
        'current_ability': current_ability,
        'potential_ability': potential_ability,
        'wage': _estimate_wage(quality, age),
        'value': _estimate_value(quality, age, potential),
        'attrs': attrs,
    }


def _estimate_value(quality, age, potential):
    # Present-day market: a 20-quality world-class player tops ~£180-200M,
    # an 18 (e.g. Declan Rice tier) lands around £110-120M.
    base = (quality ** 2.2) * 200_000
    if age <= 21:
        base *= 1.0 + (potential - quality) * 0.10
    elif age <= 27:
        base *= 1.10
    elif age <= 30:
        base *= 0.85
    elif age <= 33:
        base *= 0.45
    else:
        base *= 0.20
    return int(max(50_000, base))


def _estimate_wage(quality, age):
    # Present-day wages: elite players command £250-400K/wk.
    base = (quality ** 2) * 600
    if 24 <= age <= 30:
        base *= 1.15
    return int(max(750, base))
