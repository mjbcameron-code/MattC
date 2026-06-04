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
    Window briefing from the head coach to the DoF: the positions he wants
    strengthened, the players he'd move on, and — when he spots one — a specific
    target he'd like you to pursue. Called at the start of each transfer window.
    """
    mgr = game_state.managed_club.head_coach
    if not mgr:
        return

    needs = _position_needs(game_state)
    unwanted = _unwanted_candidates(game_state, limit=2)

    # Build the body in the coach's voice
    lines = []
    if needs:
        need_labels = [_need_label(pos) for pos in needs[:2]]
        lines.append(f"Top of my list is {' and '.join(need_labels)}.")
    if unwanted:
        names = ', '.join(p.name for p in unwanted)
        if len(unwanted) == 1:
            lines.append(f"I also think it's time we moved {names} on — "
                         f"he's not in my plans and his place could free up wages.")
        else:
            lines.append(f"I'd also look to move on {names}; they're surplus to "
                         f"my plans and clogging the wage bill.")

    # Occasionally the coach names a concrete target in a position of need
    target = None
    if needs:
        target = _suggest_target(game_state, needs[0])
        if target:
            lines.append(f"If you can get it done, {target.name} at "
                         f"{target.club.name} is exactly the {target.position} I "
                         f"want — go and get him.")

    if not lines:
        lines.append("I'm happy with the depth we have. Let's keep the group "
                     "together and only act if the right opportunity comes up.")

    headline_need = _need_label(needs[0]) if needs else "squad plans"
    add_news(game_state,
             f"{mgr.name}: transfer-window plans — {headline_need}",
             f"Head coach {mgr.name} has set out what he wants this window. "
             + ' '.join(f"'{l}'" for l in lines), 'staff')


# Light-touch ongoing personality. Fired occasionally from the match loop so the
# coach keeps talking to the DoF between windows.
COACH_FEEDBACK_CHANCE = 0.09


def maybe_coach_feedback(game_state):
    """Occasionally post a piece of head-coach feedback to the inbox."""
    import random
    mgr = game_state.managed_club.head_coach
    if not mgr:
        return
    if random.random() > COACH_FEEDBACK_CHANCE:
        return

    # Don't pile feedback on top of feedback
    from .models import NewsItem
    recent = (NewsItem.query
              .filter_by(game_state_id=game_state.id, category='staff')
              .order_by(NewsItem.id.desc()).first())
    if recent and _is_recent_coach_note(game_state, recent):
        return

    options = ['praise', 'unwanted', 'target', 'position', 'mood']
    weights = [22, 22, 18, 20, 18]
    choice = random.choices(options, weights=weights)[0]

    if choice == 'praise':
        p = _standout_player(game_state)
        if not p:
            return
        add_news(game_state, f"{mgr.name} full of praise for {p.name}",
                 f"'{p.name} has been outstanding for me. Whatever happens this "
                 f"window, I don't want to lose him — tie him down if you can.' "
                 f"The head coach clearly rates the {p.position}.", 'staff')

    elif choice == 'unwanted':
        cands = _unwanted_candidates(game_state, limit=1)
        if not cands:
            return
        p = cands[0]
        add_news(game_state, f"{mgr.name} wants {p.name} moved on",
                 f"'I'll be honest — {p.name} isn't part of how I want to play. "
                 f"I'd have no complaints if you found him a move. It would free up "
                 f"a squad place and some wages.' One for the Director of Football "
                 f"to weigh up.", 'staff')

    elif choice == 'target':
        needs = _position_needs(game_state) or [_thinnest_group(game_state)]
        target = _suggest_target(game_state, needs[0]) if needs and needs[0] else None
        if not target:
            return
        add_news(game_state, f"{mgr.name} flags {target.name} as a target",
                 f"'I've been watching {target.name} at {target.club.name}. "
                 f"He's the kind of {target.position} who'd improve us straight "
                 f"away. See what it would take.' The coach is leaving the deal "
                 f"to you.", 'staff')

    elif choice == 'position':
        needs = _position_needs(game_state)
        if not needs:
            return
        label = _need_label(needs[0])
        add_news(game_state, f"{mgr.name} reiterates need for {label}",
                 f"'I keep coming back to it — we are light for {label}. If we "
                 f"pick up an injury there we'll be exposed. I'd like the Director "
                 f"of Football to prioritise it.'", 'staff')

    else:  # mood
        sat = mgr.satisfaction or 70
        if sat >= 70:
            add_news(game_state, f"{mgr.name} happy with the working relationship",
                     f"'The Director of Football and I are pulling in the same "
                     f"direction. That's how a club should be run.' A settled mood "
                     f"in the dugout.", 'staff')
        elif sat < 45:
            add_news(game_state, f"{mgr.name} hints at frustration",
                     f"'I'd like to feel more backed. We all know where this squad "
                     f"needs work.' The head coach wants more support in the market.",
                     'staff')
        else:
            return


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


def _need_label(pos):
    return {
        'GK': 'a goalkeeper',
        'DEF': 'defensive reinforcements',
        'CB': 'a centre-back',
        'RB': 'a right-back',
        'LB': 'a left-back',
        'MID': 'a midfielder',
        'CM': 'a central midfielder',
        'AM': 'a creative midfielder',
        'ATT': 'a striker',
        'ST': 'a striker',
    }.get(pos, f'a {pos}')


def _position_needs(game_state):
    """Return a list of position-group codes the squad is light in (most-needed first)."""
    from .models import Player
    players = Player.query.filter_by(
        club_id=game_state.managed_club_id, is_youth=False).all()
    pos_count = {}
    for p in players:
        pg = _pos_group(p.position)
        pos_count[pg] = pos_count.get(pg, 0) + 1
    # (group, minimum healthy depth)
    thresholds = [('GK', 2), ('DEF', 6), ('MID', 6), ('ATT', 3)]
    needs = [(g, mn - pos_count.get(g, 0)) for g, mn in thresholds
             if pos_count.get(g, 0) < mn]
    needs.sort(key=lambda x: x[1], reverse=True)   # biggest shortfall first
    return [g for g, _ in needs]


def _thinnest_group(game_state):
    """The single most under-strength group, or None if the squad is balanced."""
    needs = _position_needs(game_state)
    return needs[0] if needs else None


def _unwanted_candidates(game_state, limit=2):
    """Fringe squad players the coach would happily move on.

    Picks the lowest-rated senior outfield players that sit outside the squad's
    core depth — preferring older ones — without recommending anyone who is
    clearly a key man.
    """
    from .models import Player
    players = [p for p in Player.query.filter_by(
        club_id=game_state.managed_club_id, is_youth=False).all()]
    if len(players) <= 16:
        return []   # squad too thin to be shedding players
    abilities = sorted((p.current_ability or 0) for p in players)
    # "core" = strongest 14; only consider players below that core for the chop
    core_cut = abilities[-14] if len(abilities) >= 14 else abilities[0]
    fringe = [p for p in players if (p.current_ability or 0) < core_cut
              and not p.transfer_listed]
    # Prefer the least useful: low ability, then older
    fringe.sort(key=lambda p: ((p.current_ability or 0), -(p.age or 0)))
    return fringe[:limit]


def _standout_player(game_state):
    """A player the coach would single out for praise (best available senior)."""
    from .models import Player
    players = [p for p in Player.query.filter_by(
        club_id=game_state.managed_club_id, is_youth=False, is_injured=False).all()]
    if not players:
        return None
    players.sort(key=lambda p: ((p.current_ability or 0), (p.morale or 0)),
                 reverse=True)
    return players[0]


def _suggest_target(game_state, position_group):
    """Find a realistic transfer target at another club in a needed position.

    Aims for someone who would improve the squad without being unattainable:
    ability around the club's current top end, never wildly beyond it.
    """
    import random
    from .models import Player, Club
    if not position_group:
        return None
    positions = _group_positions(position_group)

    mc = game_state.managed_club
    squad = [p for p in Player.query.filter_by(
        club_id=mc.id, is_youth=False).all()]
    top_ca = max((p.current_ability or 0) for p in squad) if squad else 120
    avg_ca = (sum((p.current_ability or 0) for p in squad) / len(squad)) if squad else 100
    ceiling = int(top_ca + 8)
    floor   = int(avg_ca)

    candidates = (Player.query
                  .join(Club, Player.club_id == Club.id)
                  .filter(Player.club_id != mc.id,
                          Player.is_youth == False,
                          Player.position.in_(positions),
                          Player.current_ability >= floor,
                          Player.current_ability <= ceiling)
                  .order_by(Player.current_ability.desc())
                  .limit(20).all())
    if not candidates:
        return None
    return random.choice(candidates[:10])


def _group_positions(group):
    return {
        'GK':  ['GK'],
        'DEF': ['CB', 'RB', 'LB'],
        'CB':  ['CB'],
        'RB':  ['RB'],
        'LB':  ['LB'],
        'MID': ['CM', 'RM', 'LM', 'AM'],
        'CM':  ['CM'],
        'AM':  ['AM'],
        'ATT': ['ST'],
        'ST':  ['ST'],
    }.get(group, [group])


def _is_recent_coach_note(game_state, news_item):
    """True if the most recent staff note is a coach feedback note within ~10 days."""
    try:
        from datetime import datetime
        cur = datetime.strptime(game_state.current_date, '%Y-%m-%d')
        # NewsItem stores a date string; if absent, treat as recent to be safe
        nd = getattr(news_item, 'date', None)
        if not nd:
            return False
        then = datetime.strptime(nd, '%Y-%m-%d')
        return (cur - then).days < 10
    except Exception:
        return False


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
