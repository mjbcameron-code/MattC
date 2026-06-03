"""
Player contract negotiations.

The DoF negotiates renewals directly with player agents. Agents can also
make proactive contact when a contract is running down. Negotiations run
up to 3 rounds before collapsing.
"""
import random
from datetime import datetime, timedelta

from .models import db, Player, ContractNegotiation
from .season import add_news


_FIRST = [
    'Simon', 'Mark', 'Paul', 'Keith', 'David', 'Alan', 'Phil', 'John',
    'Steve', 'Pete', 'Tony', 'Rob', 'Gary', 'Luca', 'Carlos', 'Paolo',
    'François', 'Hans', 'Stefan', 'Miguel', 'Jorge', 'Erik', 'Patrick',
    'Sean', 'Dermot', 'Colin', 'Neil', 'Ian', 'Rolf', 'Marco',
]
_LAST = [
    'Jennings', 'Townsend', 'Robson', 'Hammond', 'Fletcher', 'Bridges',
    'Mortimer', 'Carver', 'Weston', 'Harrison', 'Barker', 'Simmons',
    'Sutton', 'Ferrero', 'Delgado', 'Ricci', 'Blanc', 'Gruber',
    'Hoffmann', 'Torres', 'Santos', 'Svensson', 'Murphy', 'Dolan',
    'Walsh', 'Baxter', 'Foster', 'Chalmers', 'Keller', 'Rossi',
]


def gen_agent_name(seed):
    """Deterministic agent name derived from an integer seed."""
    rng = random.Random(seed)
    return f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"


def gen_agent_aggression(current_ability):
    """Better players attract more aggressive agents."""
    if current_ability >= 150:
        return random.randint(6, 10)
    if current_ability >= 120:
        return random.randint(5, 8)
    return random.randint(2, 6)


# ---------------------------------------------------------------------------
# Queries

def get_expiring_players(game_state):
    """Players at the managed club with ≤2 years left on contract."""
    season_year = game_state.current_season.year if game_state.current_season else 2001
    return (Player.query
            .filter_by(club_id=game_state.managed_club_id)
            .filter(Player.contract_end <= season_year + 2)
            .order_by(Player.current_ability.desc())
            .all())


def get_active_negotiations(game_state):
    return (ContractNegotiation.query
            .filter_by(game_state_id=game_state.id, status='active')
            .all())


# ---------------------------------------------------------------------------
# DoF actions

def dof_offer_renewal(game_state, player_id, wage_offer, years_offer):
    """DoF makes an offer (or counter-offer) on a player's contract."""
    player = Player.query.get(player_id)
    if not player or player.club_id != game_state.managed_club_id:
        return False, "Player not in your squad."
    if wage_offer <= 0 or years_offer < 1:
        return False, "Invalid offer — check wage and years."

    existing = ContractNegotiation.query.filter_by(
        game_state_id=game_state.id, player_id=player_id, status='active').first()

    if existing:
        existing.dof_wage_offer = wage_offer
        existing.dof_years_offer = years_offer
    else:
        current = datetime.strptime(game_state.current_date, '%Y-%m-%d')
        expires = (current + timedelta(days=30)).strftime('%Y-%m-%d')
        existing = ContractNegotiation(
            game_state_id=game_state.id,
            player_id=player_id,
            initiated_by='dof',
            status='active',
            dof_wage_offer=wage_offer,
            dof_years_offer=years_offer,
            rounds=0,
            created_date=game_state.current_date,
            expires_date=expires,
        )
        db.session.add(existing)
    db.session.flush()
    return _agent_responds(game_state, existing, player)


def dof_accept_agent_terms(game_state, neg_id):
    """DoF accepts the agent's latest counter-offer as-is."""
    neg = ContractNegotiation.query.get(neg_id)
    if not neg or neg.game_state_id != game_state.id or neg.status != 'active':
        return False, "Negotiation not found or already closed."
    player = Player.query.get(neg.player_id)
    if not player:
        return False, "Player not found."
    if not neg.agent_wage_demand or not neg.agent_years_demand:
        return False, "No agent counter-offer to accept."
    neg.dof_wage_offer = neg.agent_wage_demand
    neg.dof_years_offer = neg.agent_years_demand
    return _finalise(game_state, neg, player)


def dof_walk_away(game_state, neg_id):
    """DoF ends contract talks."""
    neg = ContractNegotiation.query.get(neg_id)
    if not neg or neg.game_state_id != game_state.id:
        return False, "Negotiation not found."
    player = Player.query.get(neg.player_id)
    neg.status = 'rejected'
    db.session.commit()
    name = player.name if player else 'Player'
    return True, f"Talks with {name}'s agent have ended."


# ---------------------------------------------------------------------------
# Periodic events (called from play_match)

def maybe_agent_approach(game_state):
    """10% chance an agent for an expiring player makes proactive contact."""
    if random.random() > 0.10:
        return
    season_year = game_state.current_season.year if game_state.current_season else 2001
    expiring = (Player.query
                .filter_by(club_id=game_state.managed_club_id)
                .filter(Player.contract_end <= season_year + 1)
                .all())
    candidates = [
        p for p in expiring
        if not ContractNegotiation.query.filter_by(
            game_state_id=game_state.id, player_id=p.id, status='active').first()
    ]
    if not candidates:
        return
    player = random.choice(candidates)
    fair_wage = _fair_wage(player)
    current = datetime.strptime(game_state.current_date, '%Y-%m-%d')
    expires = (current + timedelta(days=30)).strftime('%Y-%m-%d')
    demand_wage = int(fair_wage * random.uniform(1.00, 1.20))
    demand_years = random.choices([2, 3, 3, 4], weights=[10, 45, 30, 15])[0]
    neg = ContractNegotiation(
        game_state_id=game_state.id,
        player_id=player.id,
        initiated_by='agent',
        status='active',
        dof_wage_offer=None,
        dof_years_offer=None,
        agent_wage_demand=demand_wage,
        agent_years_demand=demand_years,
        rounds=0,
        created_date=game_state.current_date,
        expires_date=expires,
    )
    db.session.add(neg)
    db.session.commit()
    agent = player.agent_name or 'his agent'
    add_news(game_state,
             f"{agent} contacts DoF about {player.name}",
             f"{player.name}'s agent {agent} has been in touch regarding his "
             f"client's future. {player.name} has "
             f"{player.contract_end - season_year} year(s) remaining and his "
             f"agent is seeking {_fmt(demand_wage)}/wk on a "
             f"{demand_years}-year deal. Go to Contracts to respond.",
             'contract')


def expire_old_negotiations(game_state):
    """Mark negotiations past their deadline as expired."""
    active = ContractNegotiation.query.filter_by(
        game_state_id=game_state.id, status='active').all()
    for neg in active:
        if neg.expires_date and game_state.current_date > neg.expires_date:
            neg.status = 'expired'
            player = Player.query.get(neg.player_id)
            if player:
                add_news(game_state,
                         f"Contract talks with {player.name} expire",
                         f"Negotiations with {player.name}'s agent have lapsed "
                         f"without agreement. The player is now free to discuss "
                         f"terms with other clubs.", 'contract')
    db.session.commit()


# ---------------------------------------------------------------------------
# Internal helpers

def _agent_responds(game_state, neg, player):
    fair_wage = _fair_wage(player)
    wage_ratio = (neg.dof_wage_offer or 0) / max(1, fair_wage)
    years_ok = (neg.dof_years_offer or 0) >= 2

    accept_prob = 0.20
    if wage_ratio >= 1.10:
        accept_prob += 0.60
    elif wage_ratio >= 1.00:
        accept_prob += 0.45
    elif wage_ratio >= 0.90:
        accept_prob += 0.25
    elif wage_ratio >= 0.80:
        accept_prob += 0.08
    if years_ok:
        accept_prob += 0.10
    if (player.morale or 70) >= 70:
        accept_prob += 0.08
    accept_prob -= ((player.agent_aggression or 5) - 5) * 0.05
    accept_prob = max(0.05, min(0.95, accept_prob))

    if neg.rounds >= 3:
        # Final ultimatum
        if random.random() < accept_prob:
            return _finalise(game_state, neg, player)
        neg.status = 'rejected'
        db.session.commit()
        add_news(game_state,
                 f"Contract talks with {player.name} collapse",
                 f"After prolonged negotiations, {player.name}'s agent "
                 f"{player.agent_name or 'his representative'} has walked away. "
                 f"The player may seek a move when his contract expires in "
                 f"{player.contract_end}.", 'contract')
        return False, f"Talks collapsed — {player.name} may leave on a free."

    if random.random() < accept_prob:
        return _finalise(game_state, neg, player)

    # Counter-offer
    counter_wage = max(
        int(fair_wage * random.uniform(1.00, 1.12)),
        int((neg.dof_wage_offer or 0) * 1.10),
    )
    counter_years = max(neg.dof_years_offer or 2, 2)
    neg.agent_wage_demand = counter_wage
    neg.agent_years_demand = counter_years
    neg.rounds = (neg.rounds or 0) + 1
    db.session.commit()
    agent = player.agent_name or "The agent"
    add_news(game_state,
             f"{agent} counters on {player.name}'s contract",
             f"{player.name}'s agent has come back on your offer. "
             f"He is asking for {_fmt(counter_wage)}/wk on a "
             f"{counter_years}-year deal. Round {neg.rounds} of negotiations — "
             f"you can improve your offer, accept his terms, or walk away.",
             'contract')
    return False, (f"Counter: {_fmt(counter_wage)}/wk, {counter_years} yrs. "
                   f"Respond on the Contracts page.")


def _finalise(game_state, neg, player):
    season_year = game_state.current_season.year if game_state.current_season else 2001
    new_end = season_year + (neg.dof_years_offer or 2)
    player.wage = neg.dof_wage_offer
    player.contract_end = new_end
    player.morale = min(100, (player.morale or 70) + 10)
    neg.status = 'accepted'
    db.session.commit()
    agent = player.agent_name or "the agent"
    add_news(game_state,
             f"{player.name} signs new contract!",
             f"{player.name} has committed his future to "
             f"{game_state.managed_club.name}, signing a new deal until {new_end} "
             f"on {_fmt(neg.dof_wage_offer)}/week. Agent {agent} "
             f"confirmed the agreement.", 'contract')
    return True, f"{player.name} signs until {new_end}!"


def _fair_wage(player):
    from .transfers import get_transfer_value
    value = get_transfer_value(player)
    return max(1000, value // 500)


def _fmt(v):
    from .transfers import format_money
    return format_money(v)
