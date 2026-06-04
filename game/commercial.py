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

# End-of-season prize money by league level: (base for 1st, per-position drop)
_PRIZE_SCHEDULE = {
    1: (100_000_000, 3_500_000),   # Premier League
    2: (8_000_000,    280_000),    # Championship
    3: (1_500_000,     55_000),    # League One
    4: (500_000,       18_000),    # League Two
}

_FAN_POSITIVE = [
    "Brilliant result today. The lads are playing with real belief this season.",
    "That's what we came to see! If we keep this up, top four is very possible.",
    "What a performance. Loving the style of play we're seeing at the moment.",
    "Goals, entertainment, three points — this is why we love this club.",
    "Manager has got this squad firing. Cannot wait for the next one.",
]
_FAN_NEUTRAL = [
    "We'll take the point. Need a bit more going forward to push up the table.",
    "Inconsistent performances are costing us. One week brilliant, the next average.",
    "Need to be more clinical. Creating chances but not taking them.",
    "Hard to judge where we're at. Some good signs but need more consistency.",
    "Squad has potential — need to see it more regularly.",
]
_FAN_NEGATIVE = [
    "That was simply not good enough. We deserve better than this.",
    "Same story every week. No creativity, no goals, no effort.",
    "Absolutely shocking. Manager needs to take a hard look at this squad.",
    "Embarrassing performance. Something needs to change urgently.",
    "The squad is clearly not good enough. We need signings NOW.",
]
_FAN_DEMAND = [
    "We need new signings this window, no excuses. The squad is threadbare.",
    "Sign a striker or we're going nowhere this season. Fans are getting impatient.",
    "The board need to back the manager. Spend the money!",
]
_FAN_PRICE = [
    "Paying through the nose for this? Ticket prices are daylight robbery for this quality.",
    "Ordinary fans can no longer afford to come. Lower the prices or lose the fanbase.",
]
TRAINING_LABELS        = {1: 'Basic', 2: 'Decent', 3: 'Good', 4: 'Excellent', 5: 'World Class'}
STADIUM_COST_PER_SEAT  = 200           # game £ per new seat
STADIUM_QUALITY_COST   = 1_000_000    # per quality level
EXPAND_DAYS            = 90

# Candidate partners per deal type. Annual values are computed dynamically
# from club reputation (see `_sponsor_value`) so a top club like Newcastle
# earns a realistic shirt deal of tens of millions, not a few hundred grand.
_SPONSOR_POOL = {
    'shirt': [
        'SportXcel', 'TurboFuel', 'FastBet', 'ClearWater', 'AeroTech',
        'BritBuilds', 'GlobalMed', 'NordBank', 'EuroStar', 'TeamForce',
        'PromoMax', 'AlphaLager',
    ],
    'kit_supplier': [
        'ProKits', 'StrikeWear', 'NorthSport', 'AlphaGear', 'FitZone', 'EliteKit',
    ],
    'stadium_naming': [
        'MegaArena', 'InfraBuild', 'TeleCom Group', 'NordBank Park', 'AeroTech Park',
    ],
}

# (base, span) in £/yr. Value = base + span * t**1.5, where t scales with rep.
_SPONSOR_SCALE = {
    'shirt':          (1_500_000, 45_000_000),
    'kit_supplier':   (  800_000, 22_000_000),
    'stadium_naming': (  700_000, 18_000_000),
}


def _sponsor_value(deal_type, rep, rng):
    """Reputation-scaled annual sponsorship value with a little variance."""
    base, span = _SPONSOR_SCALE.get(deal_type, (500_000, 5_000_000))
    t = max(0.0, min(1.2, (rep - 40) / 55.0))
    value = base + span * (t ** 1.5)
    value *= rng.uniform(0.88, 1.12)          # partner-to-partner variance
    if value >= 10_000_000:
        return int(round(value / 500_000) * 500_000)
    if value >= 1_000_000:
        return int(round(value / 100_000) * 100_000)
    return int(round(value / 25_000) * 25_000)

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
        company = rng.choice(pool)
        value = _sponsor_value(deal_type, rep, rng)
        years = rng.choice([2, 3, 3, 4])
        offers.append({
            'type': deal_type, 'label': DEAL_LABELS.get(deal_type, deal_type),
            'company': company, 'annual_value': value, 'years': years,
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
# Matchday revenue / attendance

def _compute_fill(rep, fan_happiness, opp_rep, quality, std_price):
    """Compute stadium fill rate (0–1). High-rep clubs fill nearly every week."""
    base = min(0.92, 0.40 + rep * 0.007)
    fh = fan_happiness or 65
    if fh >= 80:    base += 0.05
    elif fh >= 65:  base += 0.02
    elif fh < 40:   base -= 0.08
    elif fh < 55:   base -= 0.03
    if opp_rep >= 80:    base += 0.06
    elif opp_rep >= 65:  base += 0.03
    base += (quality - 5) * 0.01
    price_mult = max(0.70, 1.0 - max(0, std_price - 25) * 0.004)
    return max(0.15, min(0.99, base * price_mult))


def calculate_matchday_revenue(game_state, match):
    mc = game_state.managed_club
    is_home = match.home_club_id == mc.id
    std_p = game_state.ticket_price_std or 25
    prem_p = game_state.ticket_price_premium or 45
    fan_h = game_state.fan_happiness or 65

    if is_home:
        stadium = get_or_create_stadium(mc)
        opp = match.away_club
        opp_rep = opp.reputation if opp else 50
        fill = _compute_fill(mc.reputation or 50, fan_h, opp_rep,
                             stadium.quality, std_p)
        attendance = int(stadium.capacity * fill)
        match.attendance = attendance
        std_seats = int(attendance * 0.88)
        prem_seats = attendance - std_seats
        revenue = (std_seats * std_p + prem_seats * prem_p) // 100
    else:
        home_club = match.home_club
        home_stadium = get_or_create_stadium(home_club)
        home_rep = home_club.reputation or 50
        our_rep = mc.reputation or 50
        # Approximate home crowd (away team quality boosts attendance)
        approx_fill = min(0.92, 0.40 + home_rep * 0.007) + 0.02
        if our_rep >= 80:    approx_fill += 0.06
        elif our_rep >= 65:  approx_fill += 0.03
        match.attendance = int(home_stadium.capacity * max(0.15, min(0.99, approx_fill)))
        # Away allocation only for revenue
        revenue = int(home_stadium.capacity * 0.015 * std_p) // 100

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
    mc = game_state.managed_club
    std_p = game_state.ticket_price_std or 25
    prem_p = game_state.ticket_price_premium or 45
    fill = _compute_fill(mc.reputation or 50, fh, 60, stadium.quality, std_p)
    att = int(stadium.capacity * fill)
    proj_match = (int(att * 0.88) * std_p + int(att * 0.12) * prem_p) // 100
    wage_bill = get_wage_bill(mc)
    wage_cap = game_state.wage_cap_weekly or 0
    season_rev = game_state.season_revenue or 0
    wage_annual = wage_bill * 52

    # Transfer activity this season
    transfer_in, transfer_out = _season_transfer_flows(game_state)

    # Decompose recorded revenue: sponsorship vs matchday/TV/other
    matchday_other = max(0, season_rev - sponsor_annual)

    # Full-season projection (income side)
    proj_season_income = proj_match * 19 + sponsor_annual
    # Bottom line: income − wages − net transfer spend
    net_transfer = transfer_in - transfer_out
    proj_profit = proj_season_income - wage_annual + net_transfer

    return {
        'stadium': stadium,
        'active_sponsors': active,
        'sponsor_annual': sponsor_annual,
        'training_level': lvl,
        'training_label': TRAINING_LABELS.get(lvl, 'Basic'),
        'next_training_cost': next_cost,
        'season_revenue': season_rev,
        'matchday_other': matchday_other,
        'fan_happiness': fh,
        'fan_mood': fan_mood_label(fh),
        'fan_color': fan_mood_color(fh),
        'proj_attendance': att,
        'proj_match_revenue': proj_match,
        'proj_season_revenue': proj_season_income,
        'expand_cost_per_k': STADIUM_COST_PER_SEAT * 1000,
        'quality_upgrade_cost': STADIUM_QUALITY_COST,
        'wage_bill_weekly': wage_bill,
        'wage_cap_weekly': wage_cap,
        'wage_bill_annual': wage_annual,
        'over_cap': wage_cap > 0 and wage_bill > wage_cap,
        'net_season': season_rev - wage_annual,
        'transfer_in': transfer_in,
        'transfer_out': transfer_out,
        'net_transfer': net_transfer,
        'proj_profit': proj_profit,
        'budget': mc.budget or 0,
    }


def _season_transfer_flows(game_state):
    """Sum transfer fees in/out for the managed club during the current season."""
    from .models import Transfer
    mc_id = game_state.managed_club_id
    season = game_state.current_season
    start = f"{season.year}-07-01" if season else "0000-00-00"
    rows = (Transfer.query
            .filter(Transfer.status == 'accepted')
            .filter((Transfer.to_club_id == mc_id) | (Transfer.from_club_id == mc_id))
            .filter(Transfer.transfer_date >= start)
            .all())
    income = sum((t.fee or 0) for t in rows if t.from_club_id == mc_id)
    spend = sum((t.fee or 0) for t in rows if t.to_club_id == mc_id)
    return income, spend


def get_wage_bill(club):
    """Total weekly wage bill for all senior players at the club."""
    return sum(
        p.wage for p in club.players
        if not p.is_youth and p.wage
    )


# ---------------------------------------------------------------------------
# Prize money

def _fmt(v):
    if abs(v) >= 1_000_000:
        return f'£{v/1_000_000:.1f}M'
    if abs(v) >= 1_000:
        return f'£{v/1_000:.0f}K'
    return f'£{v:,}'


def calculate_prize_money(position, league_level=1):
    """Return prize money amount without applying it."""
    level = max(1, min(4, league_level))
    base, drop = _PRIZE_SCHEDULE.get(level, (500_000, 18_000))
    return max(0, base - (position - 1) * drop)


def pay_prize_money(game_state, position, league_level=1):
    """Award end-of-season TV/prize money based on final league position."""
    prize = calculate_prize_money(position, league_level)
    mc = game_state.managed_club
    mc.budget += prize
    game_state.season_revenue = (game_state.season_revenue or 0) + prize
    pos_sfx = 'st' if position == 1 else 'nd' if position == 2 else 'rd' if position == 3 else 'th'
    add_news(game_state,
             f"League prize money: {_fmt(prize)} received",
             f"{mc.name} finish {position}{pos_sfx} and receive {_fmt(prize)} from the league's "
             f"TV rights distribution and merit payments.",
             'commercial')
    db.session.commit()
    return prize


# ---------------------------------------------------------------------------
# Fan forum

def maybe_fan_forum_post(game_state, our_score, their_score):
    """Probabilistically generate a fan reaction news item after a match."""
    fh = game_state.fan_happiness or 65
    result = ('win' if our_score > their_score else
              'draw' if our_score == their_score else 'loss')
    chances = {'win': 0.38, 'draw': 0.50, 'loss': 0.68}
    forced = fh < 30 or fh >= 85
    if not forced and random.random() > chances[result]:
        return

    mc = game_state.managed_club
    std = game_state.ticket_price_std or 25
    expected_p = 15 + (mc.reputation or 50) * 0.30

    if fh >= 80 or (result == 'win' and fh >= 65):
        pool = _FAN_POSITIVE
    elif fh < 40 or (result == 'loss' and fh < 55):
        pool = list(_FAN_NEGATIVE)
        if fh < 35:
            pool += _FAN_DEMAND
    else:
        pool = _FAN_NEUTRAL

    if std > expected_p * 1.35 and result != 'win':
        pool = list(_FAN_PRICE) + pool

    message = random.choice(pool)
    if fh >= 80:
        headline = "Fan Forum: Supporters are delighted"
    elif fh >= 65:
        headline = "Fan Forum: Fans in good spirits"
    elif fh >= 45:
        headline = "Fan Forum: Supporters voice mixed views"
    elif fh >= 30:
        headline = "Fan Forum: Frustrated fans demand improvement"
    else:
        headline = "Fan Forum: Angry supporters call for change"

    add_news(game_state, headline, message, 'fan')


# ---------------------------------------------------------------------------
# Ticket price ongoing pressure

def tick_ticket_happiness(game_state):
    """After each home match, apply a small happiness drain for over-priced tickets."""
    mc = game_state.managed_club
    std = game_state.ticket_price_std or 25
    # Expected price bracket for this club's reputation
    expected = 15 + (mc.reputation or 50) * 0.28
    if std > expected * 1.5:
        update_fan_happiness(game_state, event=None, delta=-1)
    elif std > expected * 1.25:
        if random.random() < 0.5:  # 50% chance of drain each match
            update_fan_happiness(game_state, event=None, delta=-1)
