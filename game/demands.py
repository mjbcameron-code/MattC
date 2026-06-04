"""
Chairman / owner demand system.

Generates periodic directives that the DoF must fulfil within a deadline.
Unfulfilled demands cost board confidence; fulfilled demands reward it.
"""
import random
from datetime import datetime, timedelta
from .models import db, OwnerDemand
from .season import add_news


def maybe_generate_demand(game_state):
    """12% chance per call of issuing a new chairman directive (one active at a time)."""
    if random.random() > 0.12:
        return
    existing = OwnerDemand.query.filter_by(
        game_state_id=game_state.id, active=True).first()
    if existing:
        return

    from .models import Player
    # Board directives concern the club's overall health — finances and
    # housekeeping. Squad/position requests come from the head coach, not here.
    demand_type = random.choices(
        ['sell_listed', 'keep_wage_bill'],
        weights=[50, 50])[0]

    current = datetime.strptime(game_state.current_date, '%Y-%m-%d')
    deadline = (current + timedelta(days=56)).strftime('%Y-%m-%d')

    if demand_type == 'sell_listed':
        listed = Player.query.filter_by(
            club_id=game_state.managed_club_id, transfer_listed=True).count()
        if listed == 0:
            return  # nothing listed, skip
        description = (f"The chairman wants listed players sold to free up "
                       f"funds before {deadline}. Move on deadwood.")
        target = 'any'

    else:  # keep_wage_bill
        total = _total_wages(game_state)
        threshold = int(total * 1.05)
        description = (f"The chairman insists our total weekly wage bill "
                       f"must not exceed £{threshold:,} by {deadline}.")
        target = str(threshold)

    demand = OwnerDemand(
        game_state_id=game_state.id,
        demand_type=demand_type,
        target=target,
        description=description,
        deadline=deadline,
    )
    db.session.add(demand)

    add_news(game_state,
             f"Chairman directive — {_label(demand_type)}",
             f"The chairman has contacted you directly. {description} "
             f"Failure to comply will seriously damage board confidence.",
             'demand')
    db.session.commit()


def check_active_demands(game_state):
    """Expire overdue demands that were not fulfilled; penalise board confidence."""
    demands = OwnerDemand.query.filter_by(
        game_state_id=game_state.id, active=True, fulfilled=False).all()
    for demand in demands:
        if game_state.current_date < demand.deadline:
            continue
        # Wage-bill demand: check compliance at deadline
        if demand.demand_type == 'keep_wage_bill':
            if _total_wages(game_state) <= int(demand.target):
                _fulfill(demand, game_state)
                continue
        demand.active = False
        game_state.board_confidence = max(0, (game_state.board_confidence or 50) - 15)
        add_news(game_state,
                 "Chairman disappointed — directive not met",
                 f"The deadline has passed without the chairman's instructions "
                 f"being fulfilled. '{demand.description[:100]}' "
                 f"Board confidence has dropped significantly.", 'demand')
    db.session.commit()


def on_player_signed(game_state, position):
    """Call when the DoF signs a player to satisfy sign_position demands."""
    for demand in OwnerDemand.query.filter_by(
            game_state_id=game_state.id, demand_type='sign_position',
            active=True, fulfilled=False).all():
        if demand.target == position:
            _fulfill(demand, game_state)
            break


def on_player_sold(game_state):
    """Call when a transfer-listed player is sold."""
    for demand in OwnerDemand.query.filter_by(
            game_state_id=game_state.id, demand_type='sell_listed',
            active=True, fulfilled=False).all():
        _fulfill(demand, game_state)
        break


def get_active_demands(game_state):
    return (OwnerDemand.query
            .filter_by(game_state_id=game_state.id, active=True)
            .order_by(OwnerDemand.deadline)
            .all())


def _fulfill(demand, game_state):
    demand.fulfilled = True
    demand.active = False
    game_state.board_confidence = min(100, (game_state.board_confidence or 50) + 8)
    add_news(game_state,
             "Chairman pleased — directive fulfilled",
             f"The chairman acknowledges that his instructions have been followed. "
             f"Board confidence has improved.", 'demand')
    db.session.commit()


def _total_wages(game_state):
    from .models import Player, Manager
    pw = sum(p.wage for p in
             Player.query.filter_by(club_id=game_state.managed_club_id).all())
    mgr = game_state.managed_club.head_coach
    return pw + (mgr.wage if mgr else 0)


def _label(demand_type):
    return {'sign_position': 'Sign a player',
            'sell_listed':   'Sell listed players',
            'keep_wage_bill': 'Wage bill control'}.get(demand_type, demand_type)
