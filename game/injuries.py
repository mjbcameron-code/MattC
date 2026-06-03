"""
Injury and suspension management.
"""
import random
from .models import db, Player, Suspension, PlayerStat, NewsItem

INJURY_TYPES = [
    # (label, min_weeks, max_weeks, weight)
    ('Knock',          1,  2, 30),
    ('Minor Strain',   2,  3, 25),
    ('Hamstring',      3,  5, 15),
    ('Muscle Strain',  3,  6, 15),
    ('Ankle Sprain',   2,  4, 10),
    ('Knee Injury',    5, 12,  4),
    ('Broken Bone',    8, 16,  1),
]
_TYPES, _WEIGHTS = zip(*[(t[:3], t[3]) for t in INJURY_TYPES])


def _add_news(game_state, headline, body, category='injury'):
    if not game_state:
        return
    n = NewsItem(game_state_id=game_state.id, date=game_state.current_date,
                 headline=headline, body=body, category=category)
    db.session.add(n)


def check_match_injuries(starters, game_state):
    """Random post-match injury check for managed club starters only."""
    injured = []
    for player in starters:
        if player.is_injured or player.club_id != game_state.managed_club_id:
            continue
        # Base risk: 2.5%; reduced by stamina and strength
        risk = 0.025 * (1 + max(0, 10 - player.stamina) * 0.02
                        + max(0, 10 - player.strength) * 0.01)
        if random.random() < risk:
            kind, mn, mx = random.choices(_TYPES, weights=_WEIGHTS, k=1)[0]
            weeks = random.randint(mn, mx)
            player.is_injured = True
            player.injury_weeks = weeks
            injured.append((player, kind, weeks))
            _add_news(game_state,
                      f"Injury: {player.name} out for ~{weeks} week(s)",
                      f"{player.name} sustained a {kind.lower()} and is expected "
                      f"to be sidelined for approximately {weeks} week(s).")
    db.session.commit()
    return injured


def advance_injuries():
    """Reduce injury counters for all injured players (call once per match week)."""
    recovered = []
    for p in Player.query.filter_by(is_injured=True).all():
        p.injury_weeks = max(0, p.injury_weeks - 1)
        if p.injury_weeks == 0:
            p.is_injured = False
            recovered.append(p)
    db.session.commit()
    return recovered


def is_suspended(player_id):
    """Return True if the player currently has a match ban."""
    s = Suspension.query.filter_by(player_id=player_id).filter(
        Suspension.matches_remaining > 0).first()
    return s is not None


def reduce_suspensions():
    """Reduce all active suspension counters by 1 (call after each match)."""
    for s in Suspension.query.filter(Suspension.matches_remaining > 0).all():
        s.matches_remaining -= 1
    db.session.commit()


def _apply_ban(player_id, season_id, length, reason, game_state):
    s = Suspension.query.filter_by(player_id=player_id).first()
    if s:
        s.matches_remaining += length
        s.reason = reason
    else:
        s = Suspension(player_id=player_id, season_id=season_id,
                       matches_remaining=length, reason=reason)
        db.session.add(s)
    if game_state:
        p = Player.query.get(player_id)
        if p and p.club_id == game_state.managed_club_id:
            label = 'yellow card accumulation' if reason == 'yellow_accumulation' else 'red card'
            _add_news(game_state,
                      f"{p.name} banned for {length} match(es)",
                      f"{p.name} has been suspended for {length} match(es) "
                      f"following {label}.", 'suspension')


def process_match_discipline(events, season_id, game_state):
    """Issue bans for red cards and yellow-card accumulation thresholds."""
    for ev in events:
        pid = ev.get('player_id')
        if not pid:
            continue
        if ev['type'] == 'red_card':
            _apply_ban(pid, season_id, 3, 'red_card', game_state)
        elif ev['type'] == 'yellow_card':
            ps = PlayerStat.query.filter_by(player_id=pid,
                                            season_id=season_id).first()
            yellows = ps.yellow_cards if ps else 0
            if yellows in (5, 10, 15):
                ban = 1 if yellows == 5 else (2 if yellows == 10 else 3)
                _apply_ban(pid, season_id, ban, 'yellow_accumulation', game_state)
    db.session.commit()
