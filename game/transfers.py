import random
from .models import db, Player, Club, Transfer, NewsItem, Loan


def get_transfer_value(player):
    """Estimate market value of a player based on ability, age and potential."""
    base = player.current_ability * 100000
    age_factor = 1.0
    if player.age <= 22:
        age_factor = 1.0 + (player.potential_ability - player.current_ability) / 200
    elif player.age <= 27:
        age_factor = 1.0
    elif player.age <= 31:
        age_factor = 0.8
    elif player.age <= 35:
        age_factor = 0.5
    else:
        age_factor = 0.2
    return max(100000, int(base * age_factor))


def search_players(query='', position='', min_ability=0, max_value=999999999,
                   exclude_club_id=None, for_sale_only=False):
    """Search available players for transfer."""
    q = Player.query
    if query:
        q = q.filter(Player.name.ilike(f'%{query}%'))
    if position and position != 'All':
        q = q.filter(Player.position == position)
    if for_sale_only:
        q = q.filter(Player.transfer_listed == True)
    if min_ability:
        q = q.filter(Player.current_ability >= min_ability)
    if exclude_club_id:
        q = q.filter(Player.club_id != exclude_club_id)
    players = q.order_by(Player.current_ability.desc()).limit(100).all()
    result = []
    for p in players:
        val = get_transfer_value(p)
        if val <= max_value:
            result.append(p)
    return result


def make_offer(game_state, player_id, offer_amount):
    """Make a transfer bid for a player."""
    player = Player.query.get(player_id)
    if not player:
        return False, "Player not found."

    managed_club = game_state.managed_club
    if player.club_id == managed_club.id:
        return False, "That player already plays for your club."

    fair_value = get_transfer_value(player)
    selling_club = player.club

    # Check budget
    if offer_amount > managed_club.budget:
        return False, f"Insufficient funds. You have £{managed_club.budget:,} available."

    # AI decision: accept if offer >= 85% of fair value (or always accept if transfer listed)
    threshold = 0.70 if player.transfer_listed else 0.88
    if selling_club and selling_club.reputation > managed_club.reputation + 20:
        threshold = 0.95  # top clubs want full value

    accepted = offer_amount >= fair_value * threshold

    t = Transfer(
        player_id=player.id,
        from_club_id=selling_club.id if selling_club else None,
        to_club_id=managed_club.id,
        fee=offer_amount,
        transfer_date=game_state.current_date,
        status='accepted' if accepted else 'rejected',
    )
    db.session.add(t)

    if accepted:
        old_club = player.club
        managed_club.budget -= offer_amount
        if old_club:
            old_club.budget += offer_amount
        player.club_id = managed_club.id
        player.transfer_listed = False

        news = NewsItem(
            game_state_id=game_state.id,
            date=game_state.current_date,
            headline=f"{player.name} joins {managed_club.name}!",
            body=(f"{player.name} has completed a move to {managed_club.name} "
                  f"for £{offer_amount:,}. The {player.age}-year-old "
                  f"{player.nationality} international arrives from "
                  f"{old_club.name if old_club else 'free agency'}."),
            category='transfer',
        )
        db.session.add(news)
        db.session.commit()
        return True, f"{player.name} has signed for £{offer_amount:,}!"
    else:
        db.session.commit()
        shortfall = int(fair_value * threshold) - offer_amount
        return False, (f"Offer rejected! {selling_club.name if selling_club else 'Club'} want "
                       f"around £{int(fair_value * threshold):,} for {player.name}. "
                       f"Your bid was £{shortfall:,} short.")


def list_player_for_sale(game_state, player_id):
    """List one of your players for transfer."""
    player = Player.query.get(player_id)
    if not player or player.club_id != game_state.managed_club_id:
        return False, "Player not found in your squad."
    player.transfer_listed = True
    db.session.commit()
    return True, f"{player.name} has been listed for transfer."


def release_player(game_state, player_id):
    """Release a player from your squad (free transfer)."""
    player = Player.query.get(player_id)
    if not player or player.club_id != game_state.managed_club_id:
        return False, "Player not found in your squad."
    player.club_id = None
    player.transfer_listed = False
    db.session.commit()
    return True, f"{player.name} has been released on a free transfer."


def loan_player(game_state, player_id):
    """Loan a player to the managed club for the remainder of the season."""
    player = Player.query.get(player_id)
    if not player:
        return False, 'Player not found.'
    if player.club_id == game_state.managed_club_id:
        return False, 'That player already plays for your club.'

    # Check no active loan already exists
    existing = Loan.query.filter_by(
        player_id=player_id, loan_club_id=game_state.managed_club_id,
        season_id=game_state.current_season_id, active=True).first()
    if existing:
        return False, 'Player is already on loan to you this season.'

    parent_club = player.club

    # AI acceptance: 65% chance (free agents always OK)
    if parent_club and random.random() > 0.65:
        return False, (f'{parent_club.name} have rejected the loan request for '
                       f'{player.name}. Try again or make a permanent offer.')

    loan = Loan(
        player_id=player.id,
        parent_club_id=parent_club.id if parent_club else None,
        loan_club_id=game_state.managed_club_id,
        season_id=game_state.current_season_id,
        start_date=game_state.current_date,
        active=True,
    )
    db.session.add(loan)
    player.club_id = game_state.managed_club_id
    player.transfer_listed = False

    from .season import add_news
    add_news(game_state,
             f'{player.name} joins on loan!',
             f'{player.name} ({player.age}, {player.nationality}) has joined '
             f'{game_state.managed_club.name} on a season-long loan from '
             f'{parent_club.name if parent_club else "free agency"}.',
             'transfer')
    db.session.commit()
    return True, f'{player.name} has joined on loan for the season!'


def return_loans(game_state):
    """Return all active loan players to their parent clubs at season end."""
    loans = Loan.query.filter_by(
        loan_club_id=game_state.managed_club_id,
        season_id=game_state.current_season_id,
        active=True).all()
    returned = []
    for ln in loans:
        ln.player.club_id = ln.parent_club_id
        ln.active = False
        returned.append(ln.player.name)
    if returned:
        from .season import add_news
        add_news(game_state,
                 f'{len(returned)} loan player(s) return to parent clubs',
                 f'End of season: {", ".join(returned)} have returned to '
                 f'their respective clubs.',
                 'transfer')
    db.session.commit()
    return returned


def offer_contract(game_state, player_id):
    """Offer a 3-year contract extension with a ~10% wage rise."""
    player = Player.query.get(player_id)
    if not player or player.club_id != game_state.managed_club_id:
        return False, 'Player not in your squad.'

    season_year = game_state.current_season.year + 1
    years_left = player.contract_end - season_year

    accept_prob = (0.85 if years_left <= 1 else
                   0.62 if years_left <= 2 else
                   0.35)

    if random.random() > accept_prob:
        return False, (f'{player.name} has rejected the contract offer. '
                       f'He may be looking for a move elsewhere.')

    new_wage = int(player.wage * 1.10)
    new_end  = max(player.contract_end, season_year) + 3
    player.wage = new_wage
    player.contract_end = new_end
    player.morale = min(100, (player.morale or 70) + 5)

    from .season import add_news
    add_news(game_state,
             f'{player.name} signs new contract!',
             f'{player.name} has committed his future to '
             f'{game_state.managed_club.name}, signing a new deal until '
             f'{new_end}. New wage: {format_money(new_wage)} p/w.',
             'transfer')
    db.session.commit()
    return True, f'{player.name} has signed a new contract until {new_end}!'


def format_money(v):
    if v >= 1_000_000:
        return f'£{v/1_000_000:.1f}M'
    if v >= 1_000:
        return f'£{v/1_000:.0f}K'
    return f'£{v:,}'


def is_on_loan_to(player_id, club_id, season_id):
    """True if this player is currently on loan to club_id."""
    return bool(Loan.query.filter_by(
        player_id=player_id, loan_club_id=club_id,
        season_id=season_id, active=True).first())


def ai_transfers(game_state, current_date):
    """Simulate AI clubs occasionally signing players; also bid on the manager's listed players."""
    from game.season import add_news

    # Occasionally bid on a player listed for transfer by the managed club
    if random.random() < 0.12:
        listed = Player.query.filter_by(
            club_id=game_state.managed_club_id, transfer_listed=True).all()
        if listed:
            target = random.choice(listed)
            value = get_transfer_value(target)
            bidder = random.choice(
                Club.query.filter(Club.id != game_state.managed_club_id).all() or [None])
            if bidder and bidder.budget >= value * 0.6:
                # Accept if bid is at least 80% of value
                offer = int(value * random.uniform(0.8, 1.2))
                if offer >= value * 0.8:
                    bidder.budget -= offer
                    game_state.managed_club.budget += offer
                    target.club_id = bidder.id
                    target.transfer_listed = False
                    add_news(game_state,
                             f"{target.name} sold to {bidder.name}",
                             f"{bidder.name} have signed {target.name} for "
                             f"£{offer:,}. The fee has been added to your transfer budget.",
                             'transfers')
                    db.session.commit()
                    return

    if random.random() > 0.05:
        return
    free_agents = Player.query.filter_by(club_id=None).order_by(
        Player.current_ability.desc()).limit(20).all()
    if not free_agents:
        return
    clubs = Club.query.filter(Club.id != game_state.managed_club_id).all()
    if not clubs:
        return
    player = random.choice(free_agents[:10])
    club = random.choice(clubs)
    if club.budget >= get_transfer_value(player) * 0.5:
        value = get_transfer_value(player)
        fee = int(value * random.uniform(0.5, 0.9))
        club.budget -= fee
        player.club_id = club.id
        db.session.commit()
