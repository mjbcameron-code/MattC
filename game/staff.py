"""
Director of Football — staff management.

Handles hiring/firing the head coach, manager satisfaction tracking,
and generating manager transfer requests via the inbox.
"""
from .models import db, Manager
from .season import add_news


def get_available_managers():
    """Free-agent managers sorted by reputation descending."""
    return Manager.query.filter_by(club_id=None).order_by(
        Manager.reputation.desc()).all()


def hire_manager(game_state, manager_id):
    """Hire an available manager for the DoF's club."""
    new_mgr = Manager.query.get(manager_id)
    if not new_mgr:
        return False, "Manager not found."
    if new_mgr.club_id is not None:
        return False, "That manager is already employed."

    current = game_state.managed_club.head_coach
    if current:
        _release_manager(current)

    new_mgr.club_id = game_state.managed_club_id
    season_year = game_state.current_season.year if game_state.current_season else 2001
    new_mgr.contract_end = season_year + 3
    new_mgr.satisfaction = 75  # fresh appointment

    game_state.formation = new_mgr.preferred_formation
    game_state.tactic = _style_to_tactic(new_mgr.preferred_style)

    from game.setup import auto_pick_lineup
    auto_pick_lineup(game_state, new_mgr.preferred_formation)

    db.session.commit()

    add_news(game_state,
             f"{new_mgr.name} appointed as Head Coach",
             f"{new_mgr.name} has been appointed head coach of "
             f"{game_state.managed_club.name}. The {new_mgr.nationality} manager "
             f"prefers a {new_mgr.preferred_formation} formation with a "
             f"{new_mgr.preferred_style} approach. Wage agreed: "
             f"£{new_mgr.wage:,} per week.", 'staff')
    return True, f"{new_mgr.name} appointed."


def fire_manager(game_state, reason='results'):
    """Sack the current head coach and pay compensation."""
    mgr = game_state.managed_club.head_coach
    if not mgr:
        return False, "No manager to sack."

    season_year = game_state.current_season.year if game_state.current_season else 2001
    remaining = max(0, mgr.contract_end - season_year)
    compensation = mgr.wage * 52 * remaining // 2

    game_state.board_confidence = max(0, (game_state.board_confidence or 50) - 10)

    reason_phrases = {
        'results': 'following a run of poor results',
        'mutual':  'by mutual consent',
        'budget':  'after a disagreement over transfer strategy',
    }
    phrase = reason_phrases.get(reason, '')

    add_news(game_state,
             f"{mgr.name} sacked {phrase}".strip(),
             f"{game_state.managed_club.name} have parted ways with {mgr.name} "
             f"{phrase}. Compensation of £{compensation:,} has been agreed. "
             f"The search for a new head coach begins immediately.", 'staff')

    _release_manager(mgr)
    db.session.commit()
    return True, f"Sacked. Compensation: £{compensation:,}."


def renew_manager_contract(game_state):
    """Extend the manager's contract by two years with a 10% pay rise."""
    mgr = game_state.managed_club.head_coach
    if not mgr:
        return False, "No manager under contract."

    season_year = game_state.current_season.year if game_state.current_season else 2001
    mgr.contract_end = max(mgr.contract_end, season_year) + 2
    old_wage = mgr.wage
    mgr.wage = int(mgr.wage * 1.10)
    update_manager_satisfaction(game_state, 'contract_renewed', 20)
    db.session.commit()

    add_news(game_state,
             f"{mgr.name} signs contract extension",
             f"{mgr.name} has committed his future to "
             f"{game_state.managed_club.name}, signing until {mgr.contract_end}. "
             f"His wage rises from £{old_wage:,} to £{mgr.wage:,} per week.", 'staff')
    return True, f"Contract extended to {mgr.contract_end}."


def update_manager_satisfaction(game_state, event, delta=None):
    """Adjust the manager's satisfaction with the DoF."""
    mgr = game_state.managed_club.head_coach
    if not mgr:
        return
    DELTAS = {
        'win':                  3,
        'draw':                 1,
        'loss':                -5,
        'cup_win':              6,
        'signing_request_met': 15,
        'key_player_sold':    -15,
        'contract_renewed':    20,
        'board_pressure':     -10,
        'target_met':          10,
        'target_missed':      -10,
    }
    change = delta if delta is not None else DELTAS.get(event, 0)
    mgr.satisfaction = max(0, min(100, (mgr.satisfaction or 70) + change))


def check_manager_status(game_state):
    """
    Check whether the manager wants to resign.
    Returns True if the manager has quit (caller should re-query the club).
    """
    mgr = game_state.managed_club.head_coach
    if not mgr:
        return False

    sat = mgr.satisfaction or 70

    if sat <= 10:
        add_news(game_state,
                 f"{mgr.name} resigns",
                 f"{mgr.name} has resigned as head coach of "
                 f"{game_state.managed_club.name}, citing an irreparable breakdown "
                 f"in his working relationship with the Director of Football. "
                 f"The board are deeply concerned.", 'staff')
        game_state.board_confidence = max(0, (game_state.board_confidence or 50) - 15)
        _release_manager(mgr)
        db.session.commit()
        return True

    if sat <= 25:
        from .models import NewsItem
        recent = (NewsItem.query
                  .filter_by(game_state_id=game_state.id, category='staff')
                  .filter(NewsItem.headline.like(f'{mgr.name} unsettled%'))
                  .order_by(NewsItem.id.desc()).first())
        if not recent:
            add_news(game_state,
                     f"{mgr.name} unsettled at the club",
                     f"{mgr.name} has expressed his frustration with the direction "
                     f"at {game_state.managed_club.name}. The manager feels he is not "
                     f"being backed in the transfer market. Contract runs to "
                     f"{mgr.contract_end}.", 'staff')
    return False


def generate_manager_request(game_state):
    """
    If the squad is thin at a position, post an inbox message from the manager
    requesting reinforcements. Called at the start of each transfer window.
    """
    from .models import Player
    mgr = game_state.managed_club.head_coach
    if not mgr:
        return

    players = Player.query.filter_by(
        club_id=game_state.managed_club_id, is_injured=False).all()

    pos_count = {}
    for p in players:
        pg = _pos_group(p.position)
        pos_count[pg] = pos_count.get(pg, 0) + 1

    needs = []
    if pos_count.get('GK', 0) < 2:
        needs.append('a backup goalkeeper')
    if pos_count.get('DEF', 0) < 4:
        needs.append('defensive cover')
    if pos_count.get('MID', 0) < 4:
        needs.append('midfield reinforcements')
    if pos_count.get('ATT', 0) < 2:
        needs.append('a striker')

    if needs:
        need_str = ' and '.join(needs[:2])
        add_news(game_state,
                 f"{mgr.name}: Transfer request — {needs[0]}",
                 f"Head coach {mgr.name} has contacted the Director of Football "
                 f"ahead of the transfer window. '{need_str.capitalize()} is a "
                 f"priority. Without reinforcements I cannot guarantee we hit "
                 f"the board's targets this season.'", 'staff')


def suggest_to_manager(game_state, topic, value=None):
    """
    The DoF makes a tactical suggestion to the head coach.

    topic: 'formation' (value = formation string)
         | 'style'     (value = attacking|defensive|balanced)
         | 'youth'     (give youth a chance)
         | 'praise'    (a morale-boosting word — never rejected)

    Whether the manager agrees depends on his determination (stubbornness),
    his current satisfaction with the DoF, and his own reputation. Pushing
    suggestions he rejects erodes the relationship.
    """
    import random
    mgr = game_state.managed_club.head_coach
    if not mgr:
        return False, "There is no head coach to talk to."

    # Praise is always well received
    if topic == 'praise':
        update_manager_satisfaction(game_state, 'praise', 4)
        db.session.commit()
        add_news(game_state,
                 f"You back {mgr.name} publicly",
                 f"The Director of Football has expressed full confidence in "
                 f"{mgr.name}. The head coach appreciates the support.", 'staff')
        return True, f"{mgr.name} appreciates your backing."

    # Already doing what was suggested?
    if topic == 'formation' and value == mgr.preferred_formation:
        return False, f"{mgr.name} already sets up in a {value}."
    if topic == 'style' and value == mgr.preferred_style:
        return False, f"{mgr.name} already plays a {value} style."

    sat = mgr.satisfaction or 70
    # Base willingness, modified by stubbornness, mood and ego
    prob = 0.50
    prob += 0.30 if sat >= 70 else (-0.20 if sat < 40 else 0.0)
    prob -= (mgr.determination - 10) * 0.025          # stubborn coaches resist
    prob -= max(0, (mgr.reputation - 70)) * 0.006      # big egos resist more
    if topic == 'youth':
        prob -= 0.10                                   # coaches trust experience
    prob = max(0.10, min(0.90, prob))

    accepted = random.random() < prob

    if accepted:
        if topic == 'formation':
            mgr.preferred_formation = value
            game_state.formation = value
            from game.setup import auto_pick_lineup
            auto_pick_lineup(game_state, value)
            detail = f"switch to a {value}"
        elif topic == 'style':
            mgr.preferred_style = value
            game_state.tactic = _style_to_tactic(value)
            detail = f"adopt a more {value} approach"
        else:  # youth
            detail = "give the academy prospects more game time"
        update_manager_satisfaction(game_state, 'suggestion_accepted', 2)
        db.session.commit()
        add_news(game_state,
                 f"{mgr.name} agrees to {detail}",
                 f"After talks with the Director of Football, {mgr.name} has "
                 f"agreed to {detail}. The two appear to be working well "
                 f"together.", 'staff')
        return True, f"{mgr.name} agrees to {detail}."
    else:
        update_manager_satisfaction(game_state, 'suggestion_rejected', -3)
        db.session.commit()
        excuse = {
            'formation': "I pick the system that suits my players.",
            'style':     "We play the way I believe wins football matches.",
            'youth':     "The kids aren't ready — results come first.",
        }.get(topic, "I'll manage the team my way.")
        add_news(game_state,
                 f"{mgr.name} rejects your suggestion",
                 f"{mgr.name} has pushed back on the Director of Football's "
                 f"advice. '{excuse}' Repeatedly overruling the coach risks "
                 f"the relationship.", 'staff')
        return False, f"{mgr.name} declined: '{excuse}'"


def _release_manager(manager):
    manager.club_id = None
    manager.satisfaction = 50


def _style_to_tactic(style):
    return {'attacking': 'Attack', 'defensive': 'Defend', 'balanced': 'Normal'}.get(
        style, 'Normal')


def _pos_group(pos):
    if pos == 'GK':
        return 'GK'
    if pos in ('CB', 'RB', 'LB'):
        return 'DEF'
    if pos in ('CM', 'RM', 'LM', 'AM'):
        return 'MID'
    return 'ATT'
