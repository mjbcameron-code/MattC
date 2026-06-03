"""Board confidence and sacking system."""
from .models import db

BOARD_TARGETS = [
    (85, 'Win the Title',       1,  1),
    (75, 'Finish Top 3',        1,  3),
    (65, 'Qualify for Europe',  1,  4),
    (55, 'Finish Mid-Table',    5, 14),
    (0,  'Avoid Relegation',    1, 17),
]


def set_board_target(game_state):
    """Set board target based on club reputation and reset confidence to 50."""
    rep = game_state.managed_club.reputation
    for threshold, target, min_pos, max_pos in BOARD_TARGETS:
        if rep >= threshold:
            game_state.board_target  = target
            game_state.board_min_pos = min_pos
            game_state.board_max_pos = max_pos
            break
    game_state.board_confidence = 50
    db.session.commit()


def update_board_after_match(game_state, result, current_position):
    """
    Adjust confidence after a league result.
    result: 'W', 'D', or 'L'
    Returns True if the manager has been sacked.
    """
    if game_state.board_confidence is None:
        game_state.board_confidence = 50

    delta = {'W': 5, 'D': 0, 'L': -6}.get(result, 0)

    min_pos = game_state.board_min_pos or 1
    max_pos = game_state.board_max_pos or 17
    mid     = (min_pos + max_pos) // 2

    if current_position <= min_pos:
        delta += 2
    elif current_position <= mid:
        delta += 1
    elif current_position > max_pos:
        delta -= 3

    conf = max(0, min(100, (game_state.board_confidence or 50) + delta))
    game_state.board_confidence = conf
    db.session.commit()

    from .season import add_news
    if conf <= 5:
        add_news(game_state, 'YOU HAVE BEEN SACKED',
                 f'The board have lost all confidence in your management. '
                 f'After a league position of {current_position} and a '
                 f'confidence rating of just {conf}%, the club have decided '
                 f'to part ways with you. A disappointing end to your tenure.',
                 'board')
        return True
    if conf <= 20:
        add_news(game_state, 'Board issue final warning',
                 f'The board are on the verge of making a change in the '
                 f'dugout. Confidence stands at a critical {conf}%. '
                 f'The season target is to {game_state.board_target}. '
                 f'Immediate and dramatic improvement is required.', 'board')
    elif conf <= 30:
        add_news(game_state, 'Board growing concerned',
                 f'The board are increasingly worried about the club\'s '
                 f'league position of {current_position}. Confidence is at '
                 f'{conf}%. The target remains: {game_state.board_target}.',
                 'board')
    return False
