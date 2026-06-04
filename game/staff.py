"""
Director of Football — staff management.

Handles hiring/firing the head coach, manager satisfaction tracking,
manager meetings, and generating manager transfer requests via the inbox.
"""
from .models import db, Manager
from .season import add_news


# ---------------------------------------------------------------------------
# Meeting topics
# ---------------------------------------------------------------------------

MEETING_TOPICS = {
    'form_review': {
        'title': 'Form Review',
        'opener': "Results haven't been good enough recently. I need to know we're aligned on how to fix this.",
        'choices': [
            {'key': 'back_manager',    'label': "I back you completely — keep doing it your way",
             'sat_delta': 4,  'board_delta': -1},
            {'key': 'collaborate',     'label': "Let's look at it together and work out what's changed",
             'sat_delta': 2,  'board_delta': 1},
            {'key': 'reinforce',       'label': "We'll bring in reinforcements — I'll prioritise new signings",
             'sat_delta': 1,  'board_delta': 2},
            {'key': 'ultimatum',       'label': "Results must improve immediately — this cannot continue",
             'sat_delta': -5, 'board_delta': 3,  '_note': 'det_rep_penalty'},
        ],
    },
    'tactics_freedom': {
        'title': 'Tactical Autonomy',
        'opener': "I want to be sure I have the freedom to manage the team exactly how I see fit, without interference.",
        'choices': [
            {'key': 'full_freedom',    'label': "You have complete control — that's always been my position",
             'sat_delta': 5,  'board_delta': -2},
            {'key': 'guided_freedom',  'label': "You run the team — I'll only raise things if I see a real issue",
             'sat_delta': 2,  'board_delta': 0},
            {'key': 'club_first',      'label': "The club has a playing identity we all need to respect",
             'sat_delta': -2, 'board_delta': 1,  '_note': 'tac_det_penalty'},
            {'key': 'override',        'label': "I need you to follow my specific direction on tactics",
             'sat_delta': -5, 'board_delta': 2,  '_note': 'tac_det_rep_penalty'},
        ],
    },
    'transfer_targets': {
        'title': 'Transfer Priorities',
        'opener': "I want us to be aligned on who we're targeting this window. These are the positions I need covered.",
        'choices': [
            {'key': 'agree_priorities','label': "Agreed — I'll focus the budget on your priorities",
             'sat_delta': 4,  'board_delta': 0},
            {'key': 'joint_shortlist', 'label': "Let's build a joint shortlist and agree the top targets together",
             'sat_delta': 3,  'board_delta': 1},
            {'key': 'budget_limit',    'label': "We're constrained this window — I'll do the best I can",
             'sat_delta': -1, 'board_delta': 0},
            {'key': 'dof_leads',       'label': "The DoF leads on recruitment — I'll keep you informed",
             'sat_delta': -2, 'board_delta': 1,  '_note': 'det_penalty'},
        ],
    },
    'squad_philosophy': {
        'title': 'Club Playing Identity',
        'opener': "I need the recruitment to reflect how I want to play. I don't want players who don't fit my system.",
        'choices': [
            {'key': 'align_fully',     'label': "Your system drives all our recruitment decisions",
             'sat_delta': 4,  'board_delta': -1},
            {'key': 'middle_ground',   'label': "We'll balance your needs with the club's long-term vision",
             'sat_delta': 2,  'board_delta': 1},
            {'key': 'board_mandate',   'label': "The board have set playing values — we all work within them",
             'sat_delta': -3, 'board_delta': 2,  '_note': 'det_penalty'},
            {'key': 'dof_vision',      'label': "My vision for this club goes beyond any one manager's preferences",
             'sat_delta': -4, 'board_delta': 1,  '_note': 'tac_rep_penalty'},
        ],
    },
    'check_in': {
        'title': 'Regular Check-in',
        'opener': "I just want to touch base. How do you see things going at the club right now?",
        'choices': [
            {'key': 'positive_energy', 'label': "Really positive — I think we're building something special here",
             'sat_delta': 3,  'board_delta': 0},
            {'key': 'future_plans',    'label': "Good — and I want to talk about where we take the club next",
             'sat_delta': 2,  'board_delta': 1},
            {'key': 'raise_targets',   'label': "Solid progress, but I think we can aim even higher",
             'sat_delta': 1,  'board_delta': 1},
            {'key': 'formal_review',   'label': "It's been mixed. Let's be honest about what hasn't worked",
             'sat_delta': -2, 'board_delta': 1,  '_note': 'rep_penalty'},
        ],
    },
    'contract_talks': {
        'title': 'Contract Discussion',
        'opener': "My contract is coming up. I need to know where I stand with the club going forward.",
        'choices': [
            {'key': 'extend_warmly',   'label': "I want you here long-term — let's agree an extension now",
             'sat_delta': 6,  'board_delta': 0},
            {'key': 'conditional',     'label': "I'd like to extend, but it depends on how the season finishes",
             'sat_delta': 1,  'board_delta': 1},
            {'key': 'wait_and_see',    'label': "Let's revisit this properly at the end of the season",
             'sat_delta': -2, 'board_delta': 0},
            {'key': 'no_extension',    'label': "I'm not planning to extend your contract at this stage",
             'sat_delta': -8, 'board_delta': 1,  '_note': 'det_rep_penalty'},
        ],
    },
}


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


# Confrontational meeting responses the manager will hold against the DoF.
_CONFRONTATIONAL_CHOICES = {
    'ultimatum', 'override', 'dof_leads', 'board_mandate',
    'dof_vision', 'no_extension', 'formal_review',
}


def recent_friction(game_state, limit=4):
    """Count confrontational meeting outcomes among the manager's last few meetings.

    A manager 'remembers' how he's been treated: repeated hard lines build
    resentment that makes him quicker to walk away.
    """
    from .models import ManagerMeeting
    mgr = game_state.managed_club.head_coach
    if not mgr:
        return 0
    recent = (ManagerMeeting.query
              .filter_by(game_state_id=game_state.id, manager_id=mgr.id,
                         status='resolved')
              .order_by(ManagerMeeting.id.desc())
              .limit(limit).all())
    return sum(1 for m in recent
               if m.resolved_choice in _CONFRONTATIONAL_CHOICES)


def check_manager_status(game_state):
    """
    Check whether the manager wants to resign.
    Returns True if the manager has quit (caller should re-query the club).

    Sustained friction matters: a manager who has been repeatedly overruled
    or undermined in meetings will walk at a higher satisfaction threshold
    than one who's merely having a rough patch.
    """
    mgr = game_state.managed_club.head_coach
    if not mgr:
        return False

    sat = mgr.satisfaction or 70

    # Friction raises the bar at which the manager resigns. Each confrontational
    # meeting in recent memory lifts the resignation threshold (det-resistant
    # managers in particular won't tolerate being bossed around).
    friction = recent_friction(game_state)
    resign_threshold = 10
    if friction >= 3:
        resign_threshold = 22
    elif friction >= 2:
        resign_threshold = 16

    # A strong-willed, high-reputation manager is prouder and walks sooner
    # once the relationship has soured.
    if friction >= 2 and ((mgr.determination or 10) >= 15 or (mgr.reputation or 50) >= 80):
        resign_threshold += 4

    if sat <= resign_threshold and friction >= 2:
        add_news(game_state,
                 f"{mgr.name} resigns over breakdown with the board",
                 f"{mgr.name} has walked away from "
                 f"{game_state.managed_club.name}. Sources point to a series of "
                 f"meetings in which the {mgr.nationality} coach felt overruled and "
                 f"undermined by the Director of Football. 'A manager has to feel "
                 f"backed,' said one insider. 'He didn't.'", 'staff')
        game_state.board_confidence = max(0, (game_state.board_confidence or 50) - 12)
        _release_manager(mgr)
        db.session.commit()
        return True

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


# ---------------------------------------------------------------------------
# Manager meeting system
# ---------------------------------------------------------------------------

def _personality_mod(manager, topic, choice_key):
    """Return a satisfaction modifier based on manager personality and choice."""
    det = manager.determination or 10
    tac = manager.tactical_ability or 10
    man = manager.man_management or 10
    rep = manager.reputation or 50
    mod = 0

    # High determination resists being challenged or overruled
    if choice_key in ('ultimatum', 'override', 'dof_leads', 'board_mandate', 'dof_vision', 'no_extension'):
        if det >= 15:
            mod -= 3
        elif det >= 12:
            mod -= 1

    # Tactical managers resist tactical interference
    if topic == 'tactics_freedom' and choice_key in ('override', 'club_first'):
        if tac >= 15:
            mod -= 3
        elif tac >= 12:
            mod -= 1

    # High-reputation managers expect deference
    if choice_key in ('ultimatum', 'override', 'no_extension', 'dof_vision', 'formal_review'):
        if rep >= 70:
            mod -= 2
        if rep >= 85:
            mod -= 2

    # Good man-managers respond well to collaborative, warm approaches
    if choice_key in ('collaborate', 'back_manager', 'align_fully', 'extend_warmly',
                      'positive_energy', 'joint_shortlist', 'agree_priorities'):
        if man >= 15:
            mod += 2
        elif man >= 12:
            mod += 1

    return mod


def _apply_note_penalty(manager, note):
    """Return additional sat_delta penalty from the choice note field."""
    det = manager.determination or 10
    tac = manager.tactical_ability or 10
    rep = manager.reputation or 50
    penalty = 0
    if note == 'det_rep_penalty':
        if det >= 12:
            penalty -= 1
        if rep >= 70:
            penalty -= 1
    elif note == 'tac_det_penalty':
        if tac >= 14:
            penalty -= 1
        if det >= 14:
            penalty -= 1
    elif note == 'tac_det_rep_penalty':
        if tac >= 14:
            penalty -= 2
        if det >= 14:
            penalty -= 1
        if rep >= 70:
            penalty -= 1
    elif note == 'det_penalty':
        if det >= 12:
            penalty -= 1
    elif note == 'tac_rep_penalty':
        if tac >= 14:
            penalty -= 1
        if rep >= 70:
            penalty -= 1
    elif note == 'rep_penalty':
        if rep >= 65:
            penalty -= 1
    return penalty


def maybe_schedule_meeting(game_state):
    """After each match, possibly schedule a DoF–Manager meeting."""
    import random
    mgr = game_state.managed_club.head_coach
    if not mgr:
        return

    from .models import ManagerMeeting
    # Only one pending meeting at a time
    pending = ManagerMeeting.query.filter_by(
        game_state_id=game_state.id, status='pending').first()
    if pending:
        return

    # Cooldown: don't schedule if one resolved in last 21 days
    last = (ManagerMeeting.query
            .filter_by(game_state_id=game_state.id, status='resolved')
            .order_by(ManagerMeeting.id.desc()).first())
    if last and last.scheduled_date:
        try:
            from datetime import datetime
            last_dt = datetime.strptime(last.scheduled_date, '%Y-%m-%d')
            cur_dt = datetime.strptime(game_state.current_date, '%Y-%m-%d')
            if (cur_dt - last_dt).days < 21:
                return
        except Exception:
            pass

    # Gather context
    from .models import Match as _Match
    recent = (_Match.query
              .filter_by(season_id=game_state.current_season_id, played=True)
              .filter(
                  (_Match.home_club_id == game_state.managed_club_id) |
                  (_Match.away_club_id == game_state.managed_club_id))
              .order_by(_Match.id.desc()).limit(5).all())
    losses = sum(1 for m in recent
                 if _match_result_for(m, game_state.managed_club_id) == 'L')

    season_year = game_state.current_season.year if game_state.current_season else 2025
    contract_remaining = (mgr.contract_end or (season_year + 2)) - season_year

    try:
        from datetime import datetime as _dt
        cur_month = _dt.strptime(game_state.current_date, '%Y-%m-%d').month
    except Exception:
        cur_month = 8

    board_conf = game_state.board_confidence or 50

    # Pick topic and trigger probability
    topic = None
    prob = 0.0
    board_forced = False

    # The board can force a crisis meeting when confidence has collapsed and
    # results are poor — this is not optional and lands with extra weight.
    if board_conf < 30 and losses >= 2:
        topic = 'form_review'
        prob = 0.80
        board_forced = True
    elif losses >= 3:
        topic = 'form_review'
        prob = 0.65
    elif contract_remaining <= 1:
        topic = 'contract_talks'
        prob = 0.50
    elif cur_month in (1, 7, 8):
        topic = 'transfer_targets'
        prob = 0.38
    else:
        topic = random.choices(
            ['check_in', 'tactics_freedom', 'squad_philosophy', 'check_in'],
            weights=[35, 25, 22, 18])[0]
        prob = 0.15

    if random.random() >= prob:
        return

    meeting = ManagerMeeting(
        game_state_id=game_state.id,
        manager_id=mgr.id,
        topic=topic,
        scheduled_date=game_state.current_date,
        status='pending',
    )
    db.session.add(meeting)
    db.session.commit()

    title = MEETING_TOPICS[topic]['title']
    if board_forced:
        add_news(game_state,
                 f"Board orders crisis meeting with {mgr.name}",
                 f"With confidence at a low ebb and results sliding, the board "
                 f"have instructed the Director of Football to sit down with "
                 f"{mgr.name} for a {title.lower()}. How you handle it will be "
                 f"noted upstairs. Respond from the Staff page.",
                 'staff')
    else:
        add_news(game_state,
                 f"{mgr.name} has requested a meeting — {title}",
                 f"{mgr.name} has asked for a meeting to discuss {title.lower()}. "
                 f"Head to the Staff page to respond.",
                 'staff')


def get_pending_meetings(game_state):
    from .models import ManagerMeeting
    return ManagerMeeting.query.filter_by(
        game_state_id=game_state.id, status='pending'
    ).order_by(ManagerMeeting.id).all()


def resolve_meeting(game_state, meeting_id, choice_key):
    """Apply consequences of the DoF's chosen response to a manager meeting."""
    from .models import ManagerMeeting
    meeting = ManagerMeeting.query.get(meeting_id)
    if not meeting or meeting.status != 'pending':
        return False, "Meeting not found or already resolved."

    mgr = game_state.managed_club.head_coach
    if not mgr:
        meeting.status = 'resolved'
        db.session.commit()
        return False, "No head coach."

    topic_data = MEETING_TOPICS.get(meeting.topic)
    if not topic_data:
        return False, "Unknown meeting topic."

    choice = next((c for c in topic_data['choices'] if c['key'] == choice_key), None)
    if not choice:
        return False, "Invalid choice."

    # Base deltas + personality modifier + note penalty
    sat_delta = (choice['sat_delta']
                 + _personality_mod(mgr, meeting.topic, choice_key)
                 + _apply_note_penalty(mgr, choice.get('_note')))
    board_delta = choice['board_delta']

    update_manager_satisfaction(game_state, 'meeting', sat_delta)
    game_state.board_confidence = max(0, min(100,
        (game_state.board_confidence or 50) + board_delta))

    meeting.status = 'resolved'
    meeting.resolved_choice = choice_key
    db.session.commit()

    # Post news reflecting the tone
    _post_meeting_news(game_state, mgr, meeting.topic, sat_delta, topic_data['title'])

    outcome = ('went well' if sat_delta >= 3
               else 'was constructive' if sat_delta >= 0
               else 'created some tension' if sat_delta >= -3
               else 'did not go well')
    return True, f"Meeting {outcome}."


def _post_meeting_news(game_state, mgr, topic, sat_delta, title):
    if sat_delta >= 4:
        mood, detail = "left satisfied", f"aligned with the DoF's approach"
    elif sat_delta >= 1:
        mood, detail = "seemed content", "appreciated the conversation"
    elif sat_delta >= -1:
        mood, detail = "was measured", "acknowledged the DoF's position"
    elif sat_delta >= -4:
        mood, detail = "was not entirely happy", "has reservations about the direction"
    else:
        mood, detail = "left unhappy", "and the DoF are pulling in different directions"

    add_news(game_state,
             f"Meeting with {mgr.name} ({title}) — he {mood}",
             f"{mgr.name} {detail}.", 'staff')


def _match_result_for(match, club_id):
    if match.home_club_id == club_id:
        our, their = match.home_score or 0, match.away_score or 0
    else:
        our, their = match.away_score or 0, match.home_score or 0
    if our > their:
        return 'W'
    if our == their:
        return 'D'
    return 'L'
