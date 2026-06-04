"""Board confidence and expectations system.

The board sets a realistic season objective anchored to the club's stature
(reputation) and judges the Director of Football against an *acceptable range*,
not a single must-win position. Finishing within — or above — that range keeps
the board happy. The DoF only comes under real pressure for sustained
under-performance below the acceptable floor, and even then the expectation is
that the DoF acts (new coach, new players) rather than being summarily sacked.
"""
from .models import db

# (reputation_threshold, objective_text, aspiration_pos, acceptable_floor_pos)
#   aspiration_pos  — the finish the board dreams of (meeting it delights them)
#   acceptable_floor_pos — finishing at or above this keeps the board content
BOARD_TARGETS = [
    (90, 'Win the league title',                    1,  4),
    (85, 'Qualify for the Champions League',        2,  6),
    (80, 'Qualify for European football',           5,  9),
    (73, 'Finish in the top half of the table',     8, 14),
    (64, 'Secure a comfortable mid-table finish',  11, 16),
    (0,  'Avoid relegation and consolidate',       13, 20),
]

STARTING_CONFIDENCE = 60


def target_for_reputation(rep):
    """Return (objective_text, aspiration_pos, acceptable_floor_pos) for a reputation."""
    for threshold, target, min_pos, max_pos in BOARD_TARGETS:
        if rep >= threshold:
            return target, min_pos, max_pos
    return BOARD_TARGETS[-1][1], BOARD_TARGETS[-1][2], BOARD_TARGETS[-1][3]


def set_board_target(game_state):
    """Set a realistic board objective from club reputation and reset confidence."""
    rep = game_state.managed_club.reputation
    target, min_pos, max_pos = target_for_reputation(rep)
    game_state.board_target  = target
    game_state.board_min_pos = min_pos
    game_state.board_max_pos = max_pos
    game_state.board_confidence = STARTING_CONFIDENCE
    db.session.commit()


def update_board_after_match(game_state, result, current_position):
    """
    Adjust board confidence after a league result.

    Confidence is anchored to league STANDING relative to the acceptable range,
    with the individual result a secondary nudge. Sitting within (or above) the
    acceptable band keeps confidence trending upward; only dropping below the
    acceptable floor erodes it. Returns True if the DoF has been sacked.
    """
    if game_state.board_confidence is None:
        game_state.board_confidence = STARTING_CONFIDENCE

    min_pos = game_state.board_min_pos or 1
    max_pos = game_state.board_max_pos or 17

    # Standing relative to the acceptable band drives confidence
    if current_position <= min_pos:
        pos_delta = 4               # meeting or beating the aspiration
    elif current_position <= max_pos:
        pos_delta = 1               # within the acceptable range — board content
    else:
        gap = current_position - max_pos
        pos_delta = -2 - min(4, gap)   # below the floor: -3 (just under) to -6

    # Result is a minor nudge on top of standing
    result_delta = {'W': 2, 'D': 0, 'L': -1}.get(result, 0)

    delta = pos_delta + result_delta
    conf = max(0, min(100, (game_state.board_confidence or STARTING_CONFIDENCE) + delta))
    game_state.board_confidence = conf
    db.session.commit()

    from .season import add_news
    below_floor = current_position > max_pos

    # Sacking is a last resort: only sustained collapse below the acceptable
    # floor can take confidence this low, and the board still frames it as the
    # DoF having run out of road rather than a single bad result.
    if conf <= 6 and below_floor:
        add_news(game_state, 'The board have relieved you of your duties',
                 f'After a prolonged spell with the club {current_position}th — '
                 f'well below the objective to {game_state.board_target.lower()} — '
                 f'and with confidence at just {conf}%, the board have decided to '
                 f'make a change in the boardroom. They felt the situation was not '
                 f'being turned around. A disappointing end to your tenure.',
                 'board')
        return True

    if below_floor and conf <= 18:
        add_news(game_state, 'Board demand a response',
                 f'The board are seriously concerned. The club sit {current_position}th, '
                 f'short of the objective to {game_state.board_target.lower()}, and '
                 f'confidence has fallen to {conf}%. They want to see you act — '
                 f'whether that means backing the head coach in the market, changing '
                 f'the man in the dugout, or reshaping the squad. The tools are yours.',
                 'board')
    elif below_floor and conf <= 32:
        add_news(game_state, 'Board express concern over results',
                 f'The board have noted the club\'s position of {current_position}th, '
                 f'below the objective to {game_state.board_target.lower()}. '
                 f'Confidence stands at {conf}%. They expect the Director of Football '
                 f'to identify what needs to change.', 'board')
    return False
