"""
Commercial management: matchday revenue, sponsorship, stadium and training.

DoF responsibilities: set ticket prices, expand/improve the stadium,
upgrade training facilities, negotiate sponsorship deals, and keep
the fans happy — all of which affect board confidence and long-term success.
"""
import random
from datetime import datetime, timedelta
from .models import db, Stadium, SponsorDeal
from .season import add_news


TRAINING_UPGRADE_COST  = {1: 500_000, 2: 1_500_000, 3: 3_000_000, 4: 6_000_000}
TRAINING_LABELS        = {1: 'Basic', 2: 'Decent', 3: 'Good', 4: 'Excellent', 5: 'World Class'}
STADIUM_COST_PER_SEAT  = 200           # game £ per new seat
STADIUM_QUALITY_COST   = 1_000_000    # per quality level
EXPAND_DAYS            = 90

_SPONSOR_POOL = {
    'shirt': [
        ('SportXcel', 200_000), ('TurboFuel', 180_000), ('FastBet', 250_000),
        ('ClearWater', 150_000), ('AeroTech', 350_000), ('BritBuilds', 120_000),
        ('GlobalMed', 400_000), ('NordBank', 500_000), ('EuroStar', 300_000),
        ('TeamForce',  80_000), ('PromoMax', 220_000), ('AlphaLager', 160_000),
    ],
    'kit_supplier': [
        ('ProKits', 100_000), ('StrikeWear', 80_000), ('NorthSport', 120_000),
        ('AlphaGear', 150_000), ('FitZone', 60_000), ('EliteKit', 200_000),
    ],
    'stadium_naming': [
        ('MegaArena', 200_000), ('InfraBuild', 150_000), ('TeleCom Group', 250_000),
        ('NordBank Park', 300_000), ('AeroTech Park', 350_000),
    ],
}

FAN_DELTAS = {
    'win': 2, 'draw': 0, 'loss': -3, 'heavy_loss': -7,
    'cup_win': 8, 'relegation': -20, 'title': 20,
    'big_signing': 5, 'key_sold': -8,
    'ticket_hike': -8, 'ticket_cut': 6,
    'stadium_expansion': 7, 'training_upgrade': 3,
    'manager_resigned': -5, 'manager_sacked': -4,
}

DEAL_LABELS = {
    'shirt': 'Shirt Sponsor',
    'kit_supplier': 'Kit Supplier',
    'stadium_naming': 'Stadium Naming Rights',
}


# ---------------------------------------------------------------------------
# Stadium

def get_or_create_stadium(club):
    if club.stadium:
        return club.stadium
    rep = club.reputation or 50
    if rep >= 80:
        cap, qual = random.randint(40000, 65000), 8
    elif rep >= 65:
        cap, qual = random.randint(25000, 40000), 6
    elif rep >= 50:
        cap, qual = random.randint(18000, 28000), 5
    elif rep >= 35:
        cap, qual = random.randint(10000, 20000), 4
    else:
        cap, qual = random.randint(5000, 12000), 3
    s = Stadium(club_id=club.id, capacity=cap, quality=qual,
                name=f"{club.name} Ground")
    db.session.add(s)
    db.session.flush()
    return s


def start_expansion(game_state, extra_seats):
    extra_seats = max(1000, min(20000, int(extra_seats)))
    stadium = get_or_create_stadium(game_state.managed_club)
    if stadium.expansion_in_progress:
        return False, "An expansion project is already underway."
    cost = extra_seats * STADIUM_COST_PER_SEAT
    if game_state.managed_club.budget < cost:
        return False, f"Insufficient funds. This expansion costs £{cost:,}."
    game_state.managed_club.budget -= cost
    current = datetime.strptime(game_state.current_date, '%Y-%m-%d')
    complete = (current + timedelta(days=EXPAND_DAYS)).strftime('%Y-%m-%d')
    stadium.expansion_in_progress = True
    stadium.expansion_seats = extra_seats
    stadium.expansion_complete_date = complete
    update_fan_happiness(game_state, 'stadium_expansion')
    add_news(game_state,
             f"Stadium expansion approved: +{extra_seats:,} seats",
             f"Construction begins on expanding {stadium.name} by {extra_seats:,} seats "
             f"at a cost of £{cost:,}. Expected completion: {complete}. "
             f"Fans are excited at the news.", 'commercial')
    db.session.commit()
    return True, f"Expansion underway — +{extra_seats:,} seats, completing {complete}."


def upgrade_quality(game_state):
    stadium = get_or_create_stadium(game_state.managed_club)
    if stadium.quality >= 10:
        return False, "Stadium facilities are already at the maximum level."
    if game_state.managed_club.budget < STADIUM_QUALITY_COST:
        return False, f"Insufficient funds. Quality upgrade costs £{STADIUM_QUALITY_COST:,}."
    game_state.managed_club.budget -= STADIUM_QUALITY_COST
    stadium.quality += 1
    add_news(game_state,
             f"Stadium facilities upgraded to {stadium.quality}/10",
             f"{stadium.name}'s matchday facilities have been improved. "
             f"Better facilities attract higher attendance and premium ticket buyers.", 'commercial')
    db.session.commit()
    return True, f"Facilities upgraded to {stadium.quality}/10."


def check_expansion_complete(game_state):
    stadium = get_or_create_stadium(game_state.managed_club)
    if not stadium.expansion_in_progress:
        return
    if game_state.current_date >= stadium.expansion_complete_date:
        added = stadium.expansion_seats
        stadium.capacity += added
        stadium.expansion_in_progress = False
        stadium.expansion_seats = None
        stadium.expansion_complete_date = None
        add_news(game_state,
                 f"Stadium expansion complete — new capacity {stadium.capacity:,}",
                 f"The building work is finished. {stadium.name} now holds "
                 f"{stadium.capacity:,} fans — an increase of {added:,} seats. "
                 f"Matchday revenue will rise from next home fixture.", 'commercial')
        db.session.commit()


# ---------------------------------------------------------------------------
# Training

def upgrade_training(game_state):
    club = game_state.managed_club
    lvl = getattr(club, 'training_level', 1) or 1
    if lvl >= 5:
        return False, "Training facilities are already world class."
    cost = TRAINING_UPGRADE_COST.get(lvl, 9_999_999)
    if club.budget < cost:
        return False, f"Insufficient funds. Level {lvl+1} upgrade costs £{cost:,}."
    club.budget -= cost
    club.training_level = lvl + 1
    update_fan_happiness(game_state, 'training_upgrade')
    add_news(game_state,
             f"Training ground upgraded to Level {club.training_level} — "
             f"{TRAINING_LABELS[club.training_level]}",
             f"{club.name}'s training facilities are now rated "
             f"{TRAINING_LABELS[club.training_level]}. Players will develop faster "
             f"and the improved environment should boost squad morale.", 'commercial')
    db.session.commit()
    return True, f"Training upgraded to Level {club.training_level} ({TRAINING_LABELS[club.training_level]})."


# ---------------------------------------------------------------------------
# Sponsorship

def get_active_sponsors(game_state):
    return SponsorDeal.query.filter_by(game_state_id=game_state.id, active=True).all()


def get_available_offers(game_state):
    rep = game_state.managed_club.reputation or 50
    active_types = {d.deal_type for d in get_active_sponsors(game_state)}
    offers = []
    rng = random.Random(game_state.id * 31 + (game_state.season_revenue or 0) // 100_000)
    for deal_type, pool in _SPONSOR_POOL.items():
        if deal_type in active_types:
            continue
        if deal_type == 'stadium_naming':
            st = get_or_create_stadium(game_state.managed_club)
            if st.quality < 5:
                continue
        scale = 0.5 + rep / 100.0
        available = [(n, int(v * scale)) for n, v in pool if int(v * scale) >= 30_000]
        if available:
            pick = rng.choice(available[:max(1, len(available) // 2 + 1)])
            years = rng.choice([2, 3, 3, 4])
            offers.append({
                'type': deal_type, 'label': DEAL_LABELS.get(deal_type, deal_type),
                'company': pick[0], 'annual_value': pick[1], 'years': years,
            })
    return offers


def accept_sponsor(game_state, deal_type, company, annual_value, years):
    existing = SponsorDeal.query.filter_by(
        game_state_id=game_state.id, deal_type=deal_type, active=True).first()
    if existing:
        existing.active = False
    deal = SponsorDeal(game_state_id=game_state.id, deal_type=deal_type,
                       company_name=company, annual_value=annual_value,
                       seasons_remaining=years, active=True)
    db.session.add(deal)
    game_state.managed_club.budget += annual_value
    game_state.season_revenue = (game_state.season_revenue or 0) + annual_value
    db.session.commit()
    label = DEAL_LABELS.get(deal_type, deal_type)
    add_news(game_state,
             f"{company} become {label}",
             f"{company} have signed a {years}-year deal as "
             f"{game_state.managed_club.name}'s {label}, worth £{annual_value:,} per year. "
             f"The first annual payment of £{annual_value:,} has been added to the budget.",
             'commercial')
    return True, f"Deal signed: £{annual_value:,}/yr for {years} years."


def process_season_sponsors(game_state):
    """Pay ongoing deals and expire finished ones — call at season end."""
    for deal in SponsorDeal.query.filter_by(game_state_id=game_state.id, active=True).all():
        deal.seasons_remaining -= 1
        if deal.seasons_remaining <= 0:
            deal.active = False
            add_news(game_state, f"{deal.company_name} sponsorship expires",
                     f"The deal with {deal.company_name} has run its course. "
                     f"Seek a new partner from the Commercial page.", 'commercial')
        else:
            game_state.managed_club.budget += deal.annual_value
            game_state.season_revenue = (game_state.season_revenue or 0) + deal.annual_value
    db.session.commit()


# ---------------------------------------------------------------------------
# Ticket pricing

def set_ticket_prices(game_state, std_price, premium_price):
    std_price = max(5, min(100, int(std_price)))
    premium_price = max(std_price, min(200, int(premium_price)))
    old_std = game_state.ticket_price_std or 25
    if std_price > old_std * 1.20:
        update_fan_happiness(game_state, 'ticket_hike')
        msg_extra = " Fans are unhappy about the price rise."
    elif std_price < old_std * 0.85:
        update_fan_happiness(game_state, 'ticket_cut')
        msg_extra = " Fans appreciate the reduced prices."
    else:
        msg_extra = ""
    game_state.ticket_price_std = std_price
    game_state.ticket_price_premium = premium_price
    db.session.commit()
    return True, f"Ticket prices set: Standard £{std_price}, Premium £{premium_price}.{msg_extra}"


# ---------------------------------------------------------------------------
# Matchday revenue

def calculate_matchday_revenue(game_state, match):
    mc = game_state.managed_club
    is_home = match.home_club_id == mc.id
    stadium = get_or_create_stadium(mc)
    fan_h = game_state.fan_happiness or 65
    std_p = game_state.ticket_price_std or 25
    prem_p = game_state.ticket_price_premium or 45

    if is_home:
        opp = match.away_club
        opp_rep = opp.reputation if opp else 50
        fill = 0.60
        fill += 0.12 if fan_h >= 75 else (-0.12 if fan_h < 45 else 0.02)
        fill += 0.08 if opp_rep >= 75 else (0.04 if opp_rep >= 60 else 0.0)
        fill += (stadium.quality - 5) * 0.015
        fill = max(0.30, min(0.97, fill))
        attendance = int(stadium.capacity * fill)
        std_seats = int(attendance * 0.88)
        prem_seats = attendance - std_seats
        revenue = (std_seats * std_p + prem_seats * prem_p) // 100
    else:
        # Away allocation — a small share of the home ground capacity
        revenue = int(stadium.capacity * 0.015 * std_p) // 100

    mc.budget += revenue
    game_state.season_revenue = (game_state.season_revenue or 0) + revenue
    db.session.commit()
    return revenue


# ---------------------------------------------------------------------------
# Fan happiness

def update_fan_happiness(game_state, event, delta=None):
    change = delta if delta is not None else FAN_DELTAS.get(event, 0)
    game_state.fan_happiness = max(0, min(100, (game_state.fan_happiness or 65) + change))


def fan_mood_label(h):
    if h >= 80: return "Ecstatic"
    if h >= 65: return "Happy"
    if h >= 50: return "Content"
    if h >= 35: return "Frustrated"
    if h >= 20: return "Angry"
    return "Furious"


def fan_mood_color(h):
    if h >= 65: return 'var(--cm-green-light)'
    if h >= 45: return 'var(--cm-yellow)'
    return 'var(--cm-red)'


# ---------------------------------------------------------------------------
# Summary for the commercial page

def get_summary(game_state):
    stadium = get_or_create_stadium(game_state.managed_club)
    active = get_active_sponsors(game_state)
    sponsor_annual = sum(d.annual_value for d in active)
    lvl = getattr(game_state.managed_club, 'training_level', 1) or 1
    next_cost = TRAINING_UPGRADE_COST.get(lvl)
    fh = game_state.fan_happiness or 65
    # Projected home revenue per match at current prices
    fill = 0.60 + (0.12 if fh >= 75 else (-0.12 if fh < 45 else 0.02))
    fill += (stadium.quality - 5) * 0.015
    fill = max(0.30, min(0.97, fill))
    att = int(stadium.capacity * fill)
    proj_match = (int(att * 0.88) * (game_state.ticket_price_std or 25) +
                  int(att * 0.12) * (game_state.ticket_price_premium or 45)) // 100
    wage_bill = get_wage_bill(game_state.managed_club)
    wage_cap = game_state.wage_cap_weekly or 0
    return {
        'stadium': stadium,
        'active_sponsors': active,
        'sponsor_annual': sponsor_annual,
        'training_level': lvl,
        'training_label': TRAINING_LABELS.get(lvl, 'Basic'),
        'next_training_cost': next_cost,
        'season_revenue': game_state.season_revenue or 0,
        'fan_happiness': fh,
        'fan_mood': fan_mood_label(fh),
        'fan_color': fan_mood_color(fh),
        'proj_attendance': att,
        'proj_match_revenue': proj_match,
        'proj_season_revenue': proj_match * 19 + sponsor_annual,
        'expand_cost_per_k': STADIUM_COST_PER_SEAT * 1000,
        'quality_upgrade_cost': STADIUM_QUALITY_COST,
        'wage_bill_weekly': wage_bill,
        'wage_cap_weekly': wage_cap,
        'wage_bill_annual': wage_bill * 52,
        'over_cap': wage_cap > 0 and wage_bill > wage_cap,
    }


def get_wage_bill(club):
    """Total weekly wage bill for all senior players at the club."""
    return sum(
        p.wage for p in club.players
        if not p.is_youth and p.wage
    )
