"""Player morale system."""
from .models import db, Player


def apply_match_morale(game_state, our_score, opp_score,
                       starter_ids, sub_ids, scorer_ids, assister_ids):
    """Apply morale changes to the managed club's squad after a match."""
    if our_score > opp_score:
        base = 4
    elif our_score == opp_score:
        base = 1
    else:
        base = -5

    starter_set  = set(starter_ids)
    sub_set      = set(sub_ids)
    scorer_set   = set(scorer_ids)
    assister_set = set(assister_ids)

    squad = Player.query.filter_by(club_id=game_state.managed_club_id).all()
    for p in squad:
        delta = 0
        if p.id in starter_set or p.id in sub_set:
            delta += base
        else:
            delta -= 1   # unused squad member
        if p.id in scorer_set:
            delta += 8
        if p.id in assister_set:
            delta += 4
        p.morale = max(0, min(100, (p.morale or 70) + delta))

    db.session.commit()


def tick_weekly_morale(game_state):
    """Gentle weekly morale drift. Transfer-listed players lose morale."""
    squad = Player.query.filter_by(club_id=game_state.managed_club_id).all()
    for p in squad:
        m = p.morale or 70
        if m > 65:
            m -= 1
        elif m < 65:
            m += 1
        if p.transfer_listed:
            m -= 3
        p.morale = max(0, min(100, m))
    db.session.commit()


def get_morale_multiplier(player_ids):
    """
    Returns a 0.90–1.10 multiplier based on average squad morale.
    Used by the match engine to scale attack/defence ratings.
    """
    if not player_ids:
        return 1.0
    rows = Player.query.filter(Player.id.in_(player_ids)).all()
    if not rows:
        return 1.0
    avg = sum(p.morale or 70 for p in rows) / len(rows)
    return 0.90 + (avg / 100.0) * 0.20
