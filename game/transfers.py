import random
from .models import db, Player, Club, Transfer, NewsItem


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


def ai_transfers(game_state, current_date):
    """Simulate AI clubs occasionally signing players (simplified)."""
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
