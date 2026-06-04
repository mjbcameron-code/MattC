import random
from datetime import datetime, timedelta
from .models import db, Player, Club, Transfer, NewsItem, Loan, TransferBid, IncomingBid, TransferRequest


def is_window_open(date_str):
    """Return (open: bool, message: str, days: int|None).

    Windows: Summer (Jul 1 – Sep 7), January (Jan 1 – Feb 1).
    Free agents (club_id=None) can always be signed.
    """
    try:
        current = datetime.strptime(date_str, '%Y-%m-%d')
    except (ValueError, TypeError):
        return True, 'Open', None

    year = current.year
    windows = [
        (datetime(year - 1, 7, 1),  datetime(year - 1, 9, 7),  'Summer'),
        (datetime(year, 1, 1),       datetime(year, 2, 1),       'January'),
        (datetime(year, 7, 1),       datetime(year, 9, 7),       'Summer'),
        (datetime(year + 1, 1, 1),   datetime(year + 1, 2, 1),   'January'),
    ]
    for start, end, name in windows:
        if start <= current <= end:
            days_left = (end - current).days
            return True, f'{name} window — {days_left} days remaining', days_left

    future = [(s, e, n) for s, e, n in windows if s > current]
    if future:
        nxt_start, _, nxt_name = future[0]
        days_until = (nxt_start - current).days
        return False, f'Window closed — {nxt_name} window opens in {days_until} days', days_until
    return True, 'Open', None


def get_wage_bill(club):
    """Total weekly wage commitment: all players + head coach."""
    total = sum(p.wage for p in club.players)
    hc = getattr(club, 'head_coach', None)
    if hc:
        total += hc.wage
    return total


def get_transfer_value(player):
    """Estimate market value of a player based on ability, age and potential.

    Present-day scale: CA 180 (quality ~18, Declan Rice tier) ≈ £110-120M,
    CA 200 (world class) ≈ £180-200M.
    """
    q = (player.current_ability or 100) / 10.0
    base = (q ** 2.2) * 200_000
    age_factor = 1.0
    if player.age <= 22:
        age_factor = 1.0 + (player.potential_ability - player.current_ability) / 150
    elif player.age <= 27:
        age_factor = 1.10
    elif player.age <= 31:
        age_factor = 0.8
    elif player.age <= 35:
        age_factor = 0.45
    else:
        age_factor = 0.2
    return max(50_000, int(base * age_factor))


def player_interest(player, club):
    """How realistically would `player` consider joining `club`?

    Returns a tuple (interested: bool, reason: str). Based mostly on the
    reputation gap between the player's current club and the buyer — a player
    at an elite club won't drop down to a mid-table side, but a fringe player
    or one at a smaller club will look upward. The buying club's own
    reputation, European football and squad strength widen the net.
    """
    club_rep = club.reputation or 50
    cur = player.club
    if cur is None:
        return True, 'Free agent'              # free agents will talk to anyone
    if cur.id == club.id:
        return False, 'Already at club'
    player_rep = cur.reputation or 50

    # A player's personal standing: a star (high CA) at a big club is harder
    # to tempt than a squad player. Scale the effective "pull" the buyer needs.
    ca = player.current_ability or 100
    star_at_big = player_rep >= 78 and ca >= 150

    # How far below the player's current club can the buyer be?
    # Bigger clubs can reach further down; nobody reaches far up.
    gap = club_rep - player_rep

    if star_at_big:
        # Elite player — only a lateral or upward move appeals.
        if gap >= -4:
            return True, 'Would consider a move at this level'
        return False, 'Settled at a bigger club'

    # Normal player: open to a step up, a sideways move, or a small step down
    # if the buyer is clearly ambitious (high rep).
    if gap >= -18:
        return True, 'Open to the move'
    # Fringe/young players (low CA relative to club) chase game time downward.
    if ca <= 120 and gap >= -28:
        return True, 'Seeking regular football'
    return False, 'Move unrealistic — club not big enough'


def search_players(query='', position='', min_ability=0, max_value=999999999,
                   exclude_club_id=None, for_sale_only=False, buying_club=None):
    """Search available players for transfer.

    When `buying_club` is supplied, only players who would realistically
    consider the move are returned (see `player_interest`). Transfer-listed
    and free-agent players bypass the interest filter.
    """
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
    players = q.order_by(Player.current_ability.desc()).limit(250).all()
    result = []
    for p in players:
        val = get_transfer_value(p)
        if val > max_value:
            continue
        if buying_club is not None and not p.transfer_listed:
            interested, _ = player_interest(p, buying_club)
            if not interested:
                continue
        result.append(p)
        if len(result) >= 100:
            break
    return result


def make_offer(game_state, player_id, offer_amount):
    """Make a transfer bid for a player."""
    import random as _random
    player = Player.query.get(player_id)
    if not player:
        return False, "Player not found."

    managed_club = game_state.managed_club
    if player.club_id == managed_club.id:
        return False, "That player already plays for your club."

    fair_value = get_transfer_value(player)
    selling_club = player.club

    # Will the player even entertain the move? Listed players always will.
    if not player.transfer_listed:
        interested, reason = player_interest(player, managed_club)
        if not interested:
            return False, (f"{player.name} is not interested in joining "
                           f"{managed_club.name}. {reason}.")

    if offer_amount > managed_club.budget:
        return False, f"Insufficient funds. You have £{managed_club.budget:,} available."

    # --- Release clause: auto-accept ---
    if player.release_clause and offer_amount >= player.release_clause:
        return _complete_transfer(game_state, player, selling_club, offer_amount)

    # --- Acceptance threshold ---
    threshold = 0.70 if player.transfer_listed else 0.88
    if selling_club and selling_club.reputation > managed_club.reputation + 20:
        threshold = 0.95

    accepted = offer_amount >= fair_value * threshold

    if accepted:
        return _complete_transfer(game_state, player, selling_club, offer_amount)

    # --- Counter-offer zone: 60–87% of fair value ---
    low_ball = fair_value * 0.60
    if selling_club and offer_amount >= low_ball:
        counter = int(fair_value * threshold * _random.uniform(1.00, 1.05))
        bid = TransferBid(
            game_state_id=game_state.id,
            player_id=player.id,
            selling_club_id=selling_club.id,
            bid_fee=offer_amount,
            counter_fee=counter,
            status='club_countered',
            created_date=game_state.current_date,
        )
        db.session.add(bid)
        db.session.commit()
        return False, (
            f"{selling_club.name} have rejected your bid but made a counter-offer "
            f"of £{counter:,} for {player.name}. "
            f"See Pending Bids on the Transfers page to respond."
        )

    # --- Flat rejection ---
    t = Transfer(
        player_id=player.id,
        from_club_id=selling_club.id if selling_club else None,
        to_club_id=managed_club.id,
        fee=offer_amount,
        transfer_date=game_state.current_date,
        status='rejected',
    )
    db.session.add(t)
    db.session.commit()
    shortfall = int(fair_value * threshold) - offer_amount
    return False, (
        f"Offer rejected! {selling_club.name if selling_club else 'Club'} want "
        f"around £{int(fair_value * threshold):,} for {player.name}. "
        f"Your bid was £{shortfall:,} short."
    )


def accept_counter_bid(game_state, bid_id):
    """Accept a selling club's counter-offer."""
    bid = TransferBid.query.get(bid_id)
    if not bid or bid.game_state_id != game_state.id or bid.status != 'club_countered':
        return False, "Bid not found or no longer active."
    player = Player.query.get(bid.player_id)
    if not player:
        return False, "Player not found."
    if bid.counter_fee > game_state.managed_club.budget:
        return False, f"Insufficient funds. You need £{bid.counter_fee:,}."
    bid.status = 'rejected'   # close the pending bid
    db.session.flush()
    selling_club = bid.selling_club
    return _complete_transfer(game_state, player, selling_club, bid.counter_fee)


def decline_counter_bid(game_state, bid_id):
    """Walk away from a counter-offer."""
    bid = TransferBid.query.get(bid_id)
    if not bid or bid.game_state_id != game_state.id:
        return False, "Bid not found."
    player = Player.query.get(bid.player_id)
    bid.status = 'rejected'
    db.session.commit()
    name = player.name if player else 'Player'
    return True, f"You have walked away from talks over {name}."


def get_pending_bids(game_state):
    """Counter-offers from selling clubs awaiting a DoF response."""
    return TransferBid.query.filter_by(
        game_state_id=game_state.id, status='club_countered').all()


def _complete_transfer(game_state, player, selling_club, fee):
    """Finalise a transfer deal including agent fee."""
    managed_club = game_state.managed_club
    # Agent fee: 5% of fee, max £500K; free agent = no fee
    agent_fee = min(500000, int(fee * 0.05)) if selling_club else 0
    total_cost = fee + agent_fee
    if total_cost > managed_club.budget:
        agent_fee = max(0, managed_club.budget - fee)
        total_cost = fee + agent_fee

    managed_club.budget -= total_cost
    if selling_club:
        selling_club.budget += fee

    old_club = player.club
    player.club_id = managed_club.id
    player.transfer_listed = False
    player.release_clause = None   # cleared on move

    t = Transfer(
        player_id=player.id,
        from_club_id=selling_club.id if selling_club else None,
        to_club_id=managed_club.id,
        fee=fee,
        transfer_date=game_state.current_date,
        status='accepted',
    )
    db.session.add(t)

    agent_note = (f" Agent fee of £{agent_fee:,} included."
                  if agent_fee else " No agent fee — free transfer.")
    news = NewsItem(
        game_state_id=game_state.id,
        date=game_state.current_date,
        headline=f"{player.name} joins {managed_club.name}!",
        body=(f"{player.name} has completed a move to {managed_club.name} "
              f"for £{fee:,}. The {player.age}-year-old "
              f"{player.nationality} international arrives from "
              f"{old_club.name if old_club else 'free agency'}."
              + agent_note),
        category='transfer',
    )
    db.session.add(news)
    db.session.commit()
    return True, f"{player.name} has signed for £{fee:,}!" + (
        f" (Agent fee: £{agent_fee:,})" if agent_fee else "")


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


def get_free_agents(position='', min_ability=0, limit=60):
    """Players with no club, available for free."""
    q = Player.query.filter_by(club_id=None, is_youth=False)
    if position and position != 'All':
        q = q.filter(Player.position == position)
    if min_ability:
        q = q.filter(Player.current_ability >= min_ability)
    return q.order_by(Player.current_ability.desc()).limit(limit).all()


def get_transfer_listed(exclude_club_id=None, position='', limit=80):
    """Players actively listed for sale at other clubs."""
    q = Player.query.filter_by(transfer_listed=True, is_youth=False)
    if exclude_club_id:
        q = q.filter(Player.club_id != exclude_club_id)
    if position and position != 'All':
        q = q.filter(Player.position == position)
    return q.order_by(Player.current_ability.desc()).limit(limit).all()


def sign_free_agent(game_state, player_id, wage_offer, years):
    """Sign a free agent — no transfer fee, just agree personal terms."""
    player = Player.query.get(player_id)
    if not player:
        return False, "Player not found."
    if player.club_id is not None:
        return False, f"{player.name} is not a free agent."
    if player.is_youth:
        return False, "Use the academy to manage youth players."

    managed_club = game_state.managed_club
    # Expected wage: roughly CA × 500 per week, agent accepts at ~70%+ of that
    expected_wage = player.current_ability * 500
    min_acceptable = int(expected_wage * 0.65)
    if wage_offer < min_acceptable:
        return False, (
            f"{player.name}'s agent rejected the offer. He expects at least "
            f"£{min_acceptable:,}/week. (You offered £{wage_offer:,}/week.)"
        )
    if years < 1 or years > 5:
        return False, "Contract must be between 1 and 5 years."

    season_year = game_state.current_season.year if game_state.current_season else 2001
    player.club_id = managed_club.id
    player.wage = wage_offer
    player.contract_end = season_year + years
    player.morale = 75
    player.transfer_listed = False
    # Assign next available squad number
    used = {p.squad_number for p in managed_club.players if p.squad_number}
    for n in range(1, 60):
        if n not in used:
            player.squad_number = n
            break

    from .season import add_news
    add_news(game_state,
             f"{player.name} signs as a free agent!",
             f"{player.name} ({player.age}, {player.position}) has joined "
             f"{managed_club.name} on a free transfer, signing a {years}-year deal "
             f"worth £{wage_offer:,}/week.",
             'transfer')
    db.session.commit()
    return True, f"{player.name} has signed for {managed_club.name}!"


def loan_out_player(game_state, player_id):
    """Send one of your players on a development loan to an AI club."""
    player = Player.query.get(player_id)
    if not player or player.club_id != game_state.managed_club_id:
        return False, "Player not found in your squad."
    if player.is_youth:
        return False, "Promote to first team before loaning out."

    # Check not already on loan out
    existing = Loan.query.filter_by(
        player_id=player_id, parent_club_id=game_state.managed_club_id,
        season_id=game_state.current_season_id, active=True).first()
    if existing:
        return False, f"{player.name} is already on loan."

    # Pick a suitable AI club (lower or similar reputation)
    max_rep = (game_state.managed_club.reputation or 70) + 10
    candidates = Club.query.filter(
        Club.id != game_state.managed_club_id,
        Club.reputation <= max_rep,
    ).all()
    if not candidates:
        candidates = Club.query.filter(Club.id != game_state.managed_club_id).all()

    dest = random.choice(candidates) if candidates else None
    if not dest:
        return False, "No suitable clubs available for a loan right now."

    # AI clubs accept at 75% (more likely for younger players)
    accept_rate = 0.80 if player.age <= 23 else 0.65
    if random.random() > accept_rate:
        return False, (f"{dest.name} have declined the loan request for "
                       f"{player.name}. Try a different club next month.")

    loan = Loan(
        player_id=player.id,
        parent_club_id=game_state.managed_club_id,
        loan_club_id=dest.id,
        season_id=game_state.current_season_id,
        start_date=game_state.current_date,
        active=True,
    )
    db.session.add(loan)
    player.club_id = dest.id

    from .season import add_news
    add_news(game_state,
             f"{player.name} joins {dest.name} on loan.",
             f"{player.name} ({player.age}) has joined {dest.name} on a "
             f"season-long loan to gain regular first-team experience.",
             'transfer')
    db.session.commit()
    return True, f"{player.name} has joined {dest.name} on loan for the season."


def get_loaned_out(game_state):
    """Players currently loaned out from the managed club."""
    return Loan.query.filter_by(
        parent_club_id=game_state.managed_club_id,
        season_id=game_state.current_season_id,
        active=True).all()


def recall_loan(game_state, loan_id):
    """Recall a player from a loan."""
    loan = Loan.query.get(loan_id)
    if not loan or loan.parent_club_id != game_state.managed_club_id:
        return False, "Loan not found."
    player = loan.player
    player.club_id = game_state.managed_club_id
    loan.active = False
    db.session.commit()
    return True, f"{player.name} has been recalled from his loan."


def return_loaned_out(game_state):
    """Season end: return all loaned-out players back to the managed club."""
    loans = Loan.query.filter_by(
        parent_club_id=game_state.managed_club_id,
        season_id=game_state.current_season_id,
        active=True).all()
    returned = []
    for ln in loans:
        ln.player.club_id = game_state.managed_club_id
        ln.active = False
        returned.append(ln.player.name)
    if returned:
        from .season import add_news
        add_news(game_state,
                 f"{len(returned)} loan(s) completed — players return.",
                 f"End of season: {', '.join(returned)} have returned from "
                 f"their loan spells.", 'transfer')
    db.session.commit()
    return returned


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
    """Simulate AI clubs occasionally signing players; incoming bids land in DoF inbox."""
    from game.season import add_news

    window_open, _, _ = is_window_open(current_date)

    # Incoming bid on a listed player — DoF must review it.
    # Rival clubs can only approach your players while the window is open.
    if window_open and random.random() < 0.12:
        listed = Player.query.filter_by(
            club_id=game_state.managed_club_id, transfer_listed=True).all()
        if listed:
            target = random.choice(listed)
            existing = IncomingBid.query.filter_by(
                game_state_id=game_state.id, player_id=target.id,
                status='pending').first()
            if not existing:
                clubs = Club.query.filter(
                    Club.id != game_state.managed_club_id).all()
                bidder = random.choice(clubs) if clubs else None
                if bidder:
                    value = get_transfer_value(target)
                    if bidder.budget >= value * 0.5:
                        offer = int(value * random.uniform(0.70, 1.10))
                        bid = IncomingBid(
                            game_state_id=game_state.id,
                            player_id=target.id,
                            bidding_club_id=bidder.id,
                            offered_fee=offer,
                            status='pending',
                            created_date=current_date,
                        )
                        db.session.add(bid)
                        add_news(game_state,
                                 f"Bid received for {target.name}",
                                 f"{bidder.name} have submitted a bid of £{offer:,} for "
                                 f"{target.name}. Go to Transfers → Inbox to review.",
                                 'transfer')
                        db.session.commit()
                        return

    # AI clubs sign free agents
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


def get_incoming_bids(game_state):
    """Pending bids from AI clubs on the DoF's listed players."""
    return (IncomingBid.query
            .filter_by(game_state_id=game_state.id, status='pending')
            .order_by(IncomingBid.id.desc())
            .all())


def accept_incoming_bid(game_state, bid_id):
    """Accept an AI club's bid — complete the sale at the offered fee."""
    from game.season import add_news
    bid = IncomingBid.query.get(bid_id)
    if not bid or bid.game_state_id != game_state.id or bid.status != 'pending':
        return False, "Bid not found or no longer active."
    player = Player.query.get(bid.player_id)
    bidder = Club.query.get(bid.bidding_club_id)
    if not player:
        return False, "Player not found."
    if bidder and bidder.budget < bid.offered_fee:
        bid.status = 'rejected'
        db.session.commit()
        return False, f"{bidder.name if bidder else 'Club'} can no longer afford the fee."

    fee = bid.offered_fee
    game_state.managed_club.budget += fee
    if bidder:
        bidder.budget -= fee
    old_name = player.name
    player.club_id = bidder.id if bidder else None
    player.transfer_listed = False
    bid.status = 'accepted'

    t = Transfer(
        player_id=player.id,
        from_club_id=game_state.managed_club_id,
        to_club_id=bidder.id if bidder else None,
        fee=fee,
        transfer_date=game_state.current_date,
        status='accepted',
    )
    db.session.add(t)
    add_news(game_state,
             f"{old_name} sold to {bidder.name if bidder else 'Unknown'}",
             f"{old_name} has completed a move to "
             f"{bidder.name if bidder else 'an unknown club'} for £{fee:,}.",
             'transfer')
    db.session.commit()
    return True, f"{old_name} sold to {bidder.name if bidder else 'Unknown'} for £{fee:,}!"


def reject_incoming_bid(game_state, bid_id):
    """Reject an AI club's bid."""
    bid = IncomingBid.query.get(bid_id)
    if not bid or bid.game_state_id != game_state.id or bid.status != 'pending':
        return False, "Bid not found or no longer active."
    player = Player.query.get(bid.player_id)
    bidder = Club.query.get(bid.bidding_club_id)
    bid.status = 'rejected'
    db.session.commit()
    name = player.name if player else 'Player'
    club_name = bidder.name if bidder else 'Club'
    return True, f"Bid from {club_name} for {name} has been rejected."


def counter_incoming_bid(game_state, bid_id, counter_fee):
    """DoF names a price; AI club responds immediately."""
    from game.season import add_news
    bid = IncomingBid.query.get(bid_id)
    if not bid or bid.game_state_id != game_state.id or bid.status != 'pending':
        return False, "Bid not found or no longer active."
    player = Player.query.get(bid.player_id)
    bidder = Club.query.get(bid.bidding_club_id)
    if not player or not bidder:
        return False, "Player or bidding club not found."

    bid.counter_fee = counter_fee
    bid.status = 'countered'

    # AI club acceptance based on how far above their offer the counter is
    ratio = counter_fee / max(1, bid.offered_fee)
    accept = (ratio <= 1.10 or
              (ratio <= 1.25 and random.random() < 0.60) or
              (ratio <= 1.45 and random.random() < 0.25))

    if accept and bidder.budget >= counter_fee:
        game_state.managed_club.budget += counter_fee
        bidder.budget -= counter_fee
        player.club_id = bidder.id
        player.transfer_listed = False

        t = Transfer(
            player_id=player.id,
            from_club_id=game_state.managed_club_id,
            to_club_id=bidder.id,
            fee=counter_fee,
            transfer_date=game_state.current_date,
            status='accepted',
        )
        db.session.add(t)
        add_news(game_state,
                 f"{player.name} sold to {bidder.name}",
                 f"{bidder.name} accepted your asking price of £{counter_fee:,} "
                 f"for {player.name}.",
                 'transfer')
        db.session.commit()
        return True, f"{player.name} sold to {bidder.name} for £{counter_fee:,}!"

    bid.status = 'rejected'
    db.session.commit()
    return False, (f"{bidder.name} rejected your counter of £{counter_fee:,} "
                   f"for {player.name} and have walked away.")


def maybe_player_transfer_request(game_state):
    """Unhappy or ambitious players occasionally request a transfer."""
    from game.season import add_news

    if random.random() > 0.09:
        return

    season_year = game_state.current_season.year if game_state.current_season else 2025
    candidates = []

    for p in game_state.managed_club.players:
        if p.is_youth or p.transfer_listed:
            continue
        existing = TransferRequest.query.filter_by(
            game_state_id=game_state.id, player_id=p.id, status='pending').first()
        if existing:
            continue
        reasons = []
        morale = p.morale or 70
        ca = p.current_ability or 0
        if morale < 40:
            reasons.append('unhappy')
        if p.contract_end <= season_year + 1 and ca >= 120:
            reasons.append('contract_expiring')
        if morale < 55 and p.age <= 27 and ca >= 140:
            reasons.append('ambition')
        if reasons:
            candidates.append((p, random.choice(reasons)))

    if not candidates:
        return

    player, reason = random.choice(candidates)
    reason_text = {
        'unhappy': "is unhappy at the club and has requested to leave",
        'contract_expiring': "has informed the club he will not renew and wants a move",
        'ambition': "feels his ambitions exceed the club's current trajectory",
    }.get(reason, "has requested a transfer")

    req = TransferRequest(
        game_state_id=game_state.id,
        player_id=player.id,
        reason=reason,
        created_date=game_state.current_date,
        status='pending',
    )
    db.session.add(req)
    add_news(game_state,
             f"{player.name} hands in transfer request",
             f"{player.name} {reason_text}. Respond on the Transfers page to "
             f"grant or deny his request.",
             'transfer')
    db.session.commit()


def get_transfer_requests(game_state):
    return (TransferRequest.query
            .filter_by(game_state_id=game_state.id, status='pending')
            .all())


def grant_transfer_request(game_state, req_id):
    """List the player; morale nudge upward for being heard."""
    from game.season import add_news
    req = TransferRequest.query.get(req_id)
    if not req or req.game_state_id != game_state.id or req.status != 'pending':
        return False, "Request not found."
    player = Player.query.get(req.player_id)
    if not player:
        return False, "Player not found."
    req.status = 'granted'
    player.transfer_listed = True
    player.morale = min(100, (player.morale or 70) + 5)
    add_news(game_state,
             f"{player.name} listed after transfer request",
             f"Following {player.name}'s request, the club have placed him on the "
             f"transfer list and will listen to offers.",
             'transfer')
    db.session.commit()
    return True, f"{player.name} has been listed for transfer."


def deny_transfer_request(game_state, req_id):
    """Deny the request — morale hit for the player."""
    from game.season import add_news
    req = TransferRequest.query.get(req_id)
    if not req or req.game_state_id != game_state.id or req.status != 'pending':
        return False, "Request not found."
    player = Player.query.get(req.player_id)
    if not player:
        return False, "Request not found."
    req.status = 'denied'
    player.morale = max(0, (player.morale or 70) - 12)
    add_news(game_state,
             f"{player.name}'s transfer request rejected",
             f"The club has told {player.name} he is not for sale. He is unhappy "
             f"about this and it may affect his performances.",
             'transfer')
    db.session.commit()
    return True, f"{player.name}'s transfer request denied. His morale has taken a hit."
