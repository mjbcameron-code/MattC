"""
Championship Manager 01/02 clone — Flask application.

Run with:  python3 app.py
Then open:  http://localhost:5000
"""
import os
from datetime import datetime, timedelta

from flask import (Flask, render_template, request, redirect, url_for,
                   session, jsonify, flash)

from game.models import (db, League, Club, Player, Season, Match, MatchEvent,
                         Standing, PlayerStat, Transfer, NewsItem, GameState,
                         Lineup, Suspension, Loan, Manager, OwnerDemand,
                         ContractNegotiation, TransferBid, Scout, ScoutKnowledge,
                         Stadium, SponsorDeal, IncomingBid, TransferRequest,
                         MatchRating, ManagerMeeting)
from game.setup import (seed_database, new_game, auto_pick_lineup,
                       database_is_seeded)
from game import season as season_mod
from game import engine
from game import transfers as transfers_mod
from game import cups as cups_mod
from game import injuries as injuries_mod
from game import europe as europe_mod
from game import staff as staff_mod
from game import demands as demands_mod
from game import contracts as contracts_mod
from game import scouting as scouting_mod
from game import commercial as commercial_mod
from game import academy as academy_mod
from game import press as press_mod
from game import records as records_mod
from game.morale import apply_match_morale
from game.board import update_board_after_match

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'cm0102-clone-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = \
    'sqlite:///' + os.path.join(BASE_DIR, 'game.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_game_state():
    return GameState.query.first()


def require_game(f):
    """Decorator: redirect to setup if no game in progress."""
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        gs = get_game_state()
        if not gs:
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return wrapper


def get_next_any_match(gs):
    """Return the next unplayed match for the managed club (any competition)."""
    return Match.query.filter(
        Match.season_id == gs.current_season_id,
        Match.played == False,
        (Match.home_club_id == gs.managed_club_id) |
        (Match.away_club_id == gs.managed_club_id)
    ).order_by(Match.match_date).first()


@app.context_processor
def inject_globals():
    gs = get_game_state()
    unread = 0
    if gs:
        unread = NewsItem.query.filter_by(
            game_state_id=gs.id, read=False).count()
    return {'game_state': gs, 'unread_news': unread,
            'now_year': 2002}


def format_money(value):
    if value is None:
        return '£0'
    if abs(value) >= 1_000_000:
        return f'£{value / 1_000_000:.1f}M'
    if abs(value) >= 1_000:
        return f'£{value / 1_000:.0f}K'
    return f'£{value:,}'


app.jinja_env.filters['money'] = format_money


def stars_value(ca):
    """Convert a current/potential ability (CA, 1-200) to a 0.5-5.0 star rating."""
    return max(0.5, min(5.0, round((ca or 0) / 40 * 2) / 2))


def stars_html(ca):
    """Render a CA value as filled/half/empty stars (out of 5)."""
    from markupsafe import Markup
    n = stars_value(ca)
    full = int(n)
    half = 1 if (n - full) >= 0.5 else 0
    empty = 5 - full - half
    out = ('<span class="stars">'
           + '★' * full
           + ('⯨' if half else '')
           + '<span class="star-empty">' + '☆' * empty + '</span>'
           + '</span>')
    return Markup(out)


app.jinja_env.filters['stars'] = stars_value
app.jinja_env.filters['starbar'] = stars_html


def _club_initials(club):
    """Short crest initials from a club's name (e.g. 'Newcastle United' -> 'NU')."""
    name = (getattr(club, 'short_name', None) or getattr(club, 'name', '') or '?')
    skip = {'united', 'city', 'town', 'fc', 'afc', 'hotspur', 'wanderers',
            'albion', 'rovers', 'county', 'athletic', 'and', 'the', '&'}
    words = [w for w in name.replace('&', ' ').split() if w.lower() not in skip]
    if not words:
        words = name.split()
    if len(words) == 1:
        return words[0][:3].upper()
    return ''.join(w[0] for w in words[:3]).upper()


def club_crest(club, size=34):
    """Generate an inline SVG shield crest from the club's real colours + initials.

    A self-contained, license-safe stand-in for real-life crests: each club gets
    a distinctive two-tone shield badge in its actual kit colours."""
    from markupsafe import Markup
    if club is None:
        return Markup('')
    primary = getattr(club, 'primary_color', None) or '#cc0000'
    secondary = getattr(club, 'secondary_color', None) or '#ffffff'
    initials = _club_initials(club)
    # Choose readable text colour against the primary fill.
    try:
        r, g, b = (int(primary[1:3], 16), int(primary[3:5], 16), int(primary[5:7], 16))
        lum = (0.299 * r + 0.587 * g + 0.114 * b)
        text_col = '#1a1a1a' if lum > 150 else '#ffffff'
    except (ValueError, IndexError):
        text_col = '#ffffff'
    fs = max(9, int(size * 0.34))
    svg = (
        f'<svg class="crest" width="{size}" height="{size}" viewBox="0 0 40 44" '
        f'xmlns="http://www.w3.org/2000/svg" style="vertical-align:middle;flex-shrink:0;">'
        f'<path d="M2 2 H38 V24 Q38 38 20 43 Q2 38 2 24 Z" fill="{primary}" '
        f'stroke="{secondary}" stroke-width="2.5"/>'
        f'<path d="M2 2 H20 V43 Q2 38 2 24 Z" fill="{secondary}" opacity="0.18"/>'
        f'<text x="20" y="24" font-family="Arial Black, Arial, sans-serif" '
        f'font-size="{fs}" font-weight="bold" fill="{text_col}" '
        f'text-anchor="middle" dominant-baseline="middle">{initials}</text>'
        f'</svg>'
    )
    return Markup(svg)


app.jinja_env.globals['club_crest'] = club_crest


# ---------------------------------------------------------------------------
# Routes: setup / new game
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    gs = get_game_state()
    if gs:
        return redirect(url_for('dashboard'))
    return render_template('index.html')


@app.route('/new-game', methods=['GET', 'POST'])
def new_game_route():
    if not database_is_seeded():
        seed_database()

    if request.method == 'POST':
        manager_name = request.form.get('manager_name', 'Manager').strip() or 'Manager'
        club_id = int(request.form.get('club_id'))
        new_game(manager_name, club_id)
        return redirect(url_for('dashboard'))

    leagues = League.query.all()
    leagues_with_clubs = []
    for lg in leagues:
        clubs = sorted(Club.query.filter_by(league_id=lg.id).all(),
                       key=lambda c: -c.reputation)
        leagues_with_clubs.append((lg, clubs))
    return render_template('new_game.html', leagues_with_clubs=leagues_with_clubs)


@app.route('/abandon', methods=['POST'])
def abandon():
    GameState.query.delete()
    db.session.commit()
    return redirect(url_for('index'))


# ---------------------------------------------------------------------------
# Routes: dashboard
# ---------------------------------------------------------------------------

@app.route('/dashboard')
@require_game
def dashboard():
    gs = get_game_state()
    club = gs.managed_club
    next_match = get_next_any_match(gs)
    recent = season_mod.get_recent_results(gs)
    table = season_mod.get_league_table(gs.current_season_id, club.league_id)
    position = next((i + 1 for i, s in enumerate(table)
                     if s.club_id == club.id), None)
    news = NewsItem.query.filter_by(game_state_id=gs.id).order_by(
        NewsItem.id.desc()).limit(6).all()
    squad_size = Player.query.filter_by(club_id=club.id).count()
    injured = Player.query.filter_by(club_id=club.id, is_injured=True).count()

    # Squad morale summary
    squad = Player.query.filter_by(club_id=club.id).all()
    avg_morale = round(sum(p.morale or 70 for p in squad) / max(1, len(squad)))

    # Next European fixture
    next_euro = None
    all_euro = europe_mod.get_euro_matches_for_club(club.id, gs.current_season_id)
    for m in sorted(all_euro, key=lambda x: x.match_date):
        if not m.played:
            next_euro = m
            break

    wage_bill = transfers_mod.get_wage_bill(club)
    pending_meetings = staff_mod.get_pending_meetings(gs)
    return render_template('dashboard.html',
                           club=club, next_match=next_match, recent=recent,
                           table=table[:8], position=position, news=news,
                           squad_size=squad_size, injured=injured,
                           total_teams=len(table), avg_morale=avg_morale,
                           next_euro=next_euro, wage_bill=wage_bill,
                           pending_meetings=pending_meetings)


# ---------------------------------------------------------------------------
# Routes: squad / player
# ---------------------------------------------------------------------------

@app.route('/squad')
@require_game
def squad():
    gs = get_game_state()
    club = gs.managed_club
    players = Player.query.filter_by(club_id=club.id).all()
    pos_order = {'GK': 0, 'RB': 1, 'CB': 2, 'LB': 3, 'RM': 4, 'CM': 5,
                 'LM': 6, 'AM': 7, 'ST': 8}
    players.sort(key=lambda p: (pos_order.get(p.position, 9),
                                -p.current_ability))
    lineup_ids = {l.player_id for l in
                  Lineup.query.filter_by(game_state_id=gs.id).filter(
                      Lineup.slot <= 11).all()}
    stats = {}
    for ps in PlayerStat.query.filter_by(
            season_id=gs.current_season_id, club_id=club.id).all():
        stats[ps.player_id] = ps
    suspensions = {s.player_id: s.matches_remaining
                   for s in Suspension.query.filter(
                       Suspension.matches_remaining > 0).all()}
    # Loan badges: players currently on loan to us
    loan_ids = {ln.player_id for ln in Loan.query.filter_by(
        loan_club_id=club.id, season_id=gs.current_season_id,
        active=True).all()}
    return render_template('squad.html', club=club, players=players,
                           lineup_ids=lineup_ids, stats=stats,
                           suspensions=suspensions, loan_ids=loan_ids)


@app.route('/player/<int:player_id>')
@require_game
def player_detail(player_id):
    gs = get_game_state()
    player = Player.query.get_or_404(player_id)
    stats = PlayerStat.query.filter_by(
        player_id=player.id, season_id=gs.current_season_id).first()
    value = transfers_mod.get_transfer_value(player)
    on_loan = transfers_mod.is_on_loan_to(
        player.id, gs.managed_club_id, gs.current_season_id)
    managed = player.club_id == gs.managed_club_id
    if managed:
        know, tier = None, 3
    else:
        know = scouting_mod.get_knowledge(gs, player.id)
        tier = scouting_mod.knowledge_tier(know.knowledge if know else 0)
    idle_scouts = scouting_mod.get_idle_club_scouts(gs) if not managed else []
    cur_star = scouting_mod.stars(player.current_ability)
    pot_star = scouting_mod.stars(player.potential_ability)

    # Recent per-match ratings (most recent first) for the player's profile
    recent_ratings = []
    if managed or tier == 3:
        from game.models import MatchRating
        rows = (MatchRating.query.filter_by(player_id=player.id)
                .order_by(MatchRating.id.desc()).limit(6).all())
        for mr in rows:
            m = Match.query.get(mr.match_id)
            recent_ratings.append((mr, m))

    return render_template('player.html', player=player, stats=stats,
                           value=value, managed=managed,
                           on_loan=on_loan, know=know, tier=tier,
                           idle_scouts=idle_scouts, cur_star=cur_star,
                           pot_star=pot_star, recent_ratings=recent_ratings,
                           stars=scouting_mod.stars)


# ---------------------------------------------------------------------------
# Routes: tactics / lineup
# ---------------------------------------------------------------------------

@app.route('/tactics')
@require_game
def tactics():
    """Read-only view of the head coach's planned lineup."""
    gs = get_game_state()
    club = gs.managed_club
    lineups = Lineup.query.filter_by(game_state_id=gs.id).order_by(Lineup.slot).all()
    starters = [l for l in lineups if l.slot <= 11]
    subs = [l for l in lineups if l.slot > 11]
    manager = club.head_coach
    formation = (manager.preferred_formation if manager else gs.formation)
    return render_template('tactics.html', club=club, starters=starters,
                           subs=subs, manager=manager, formation=formation)


# ---------------------------------------------------------------------------
# Routes: staff management
# ---------------------------------------------------------------------------

@app.route('/staff')
@require_game
def staff():
    gs = get_game_state()
    friction = staff_mod.recent_friction(gs) if gs.managed_club.head_coach else 0
    return render_template('staff.html',
                           head_coach=gs.managed_club.head_coach,
                           available=staff_mod.get_available_managers(),
                           pending_meetings=staff_mod.get_pending_meetings(gs),
                           friction=friction,
                           club=gs.managed_club, gs=gs)


@app.route('/staff/hire/<int:manager_id>', methods=['POST'])
@require_game
def hire_manager(manager_id):
    gs = get_game_state()
    ok, msg = staff_mod.hire_manager(gs, manager_id)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('staff'))


@app.route('/staff/fire', methods=['POST'])
@require_game
def fire_manager():
    gs = get_game_state()
    ok, msg = staff_mod.fire_manager(gs)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('staff'))


@app.route('/staff/renew', methods=['POST'])
@require_game
def renew_manager():
    gs = get_game_state()
    ok, msg = staff_mod.renew_manager_contract(gs)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('staff'))


@app.route('/staff/suggest', methods=['POST'])
@require_game
def suggest_to_manager():
    gs = get_game_state()
    topic = request.form.get('topic', '')
    value = request.form.get('value') or None
    ok, msg = staff_mod.suggest_to_manager(gs, topic, value)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('staff'))


@app.route('/staff/meeting/<int:meeting_id>', methods=['GET', 'POST'])
@require_game
def manager_meeting(meeting_id):
    gs = get_game_state()
    meeting = ManagerMeeting.query.get_or_404(meeting_id)
    if meeting.game_state_id != gs.id:
        return redirect(url_for('staff'))
    if meeting.status != 'pending':
        flash('That meeting has already been resolved.', 'error')
        return redirect(url_for('staff'))

    topic_data = staff_mod.MEETING_TOPICS.get(meeting.topic, {})

    if request.method == 'POST':
        choice_key = request.form.get('choice_key', '')
        ok, msg = staff_mod.resolve_meeting(gs, meeting_id, choice_key)
        flash(msg, 'success' if ok else 'error')
        return redirect(url_for('staff'))

    return render_template('manager_meeting.html',
                           meeting=meeting, topic_data=topic_data,
                           mgr=meeting.manager, gs=gs)


# ---------------------------------------------------------------------------
# Routes: contracts
# ---------------------------------------------------------------------------

@app.route('/contracts')
@require_game
def contracts():
    gs = get_game_state()
    expiring = contracts_mod.get_expiring_players(gs)
    negotiations = contracts_mod.get_active_negotiations(gs)
    season_year = gs.current_season.year if gs.current_season else 2001
    return render_template('contracts.html', gs=gs,
                           club=gs.managed_club,
                           expiring=expiring,
                           negotiations=negotiations,
                           season_year=season_year)


@app.route('/contracts/offer/<int:player_id>', methods=['POST'])
@require_game
def contracts_offer(player_id):
    gs = get_game_state()
    try:
        wage = int(request.form.get('wage', 0))
        years = int(request.form.get('years', 2))
    except ValueError:
        flash('Invalid offer values.', 'error')
        return redirect(url_for('contracts'))
    ok, msg = contracts_mod.dof_offer_renewal(gs, player_id, wage, years)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('contracts'))


@app.route('/contracts/accept/<int:neg_id>', methods=['POST'])
@require_game
def contracts_accept(neg_id):
    gs = get_game_state()
    ok, msg = contracts_mod.dof_accept_agent_terms(gs, neg_id)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('contracts'))


@app.route('/contracts/decline/<int:neg_id>', methods=['POST'])
@require_game
def contracts_decline(neg_id):
    gs = get_game_state()
    ok, msg = contracts_mod.dof_walk_away(gs, neg_id)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('contracts'))


# ---------------------------------------------------------------------------
# Routes: scouting
# ---------------------------------------------------------------------------

@app.route('/scouting')
@require_game
def scouting():
    gs = get_game_state()
    return render_template('scouting.html', gs=gs, club=gs.managed_club,
                           club_scouts=scouting_mod.get_club_scouts(gs),
                           available=scouting_mod.get_available_scouts(),
                           shortlist=scouting_mod.get_shortlist(gs),
                           regions=scouting_mod.REGIONS,
                           stars=scouting_mod.stars,
                           tier_fn=scouting_mod.knowledge_tier)


@app.route('/scouting/hire/<int:scout_id>', methods=['POST'])
@require_game
def scouting_hire(scout_id):
    gs = get_game_state()
    ok, msg = scouting_mod.hire_scout(gs, scout_id)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('scouting'))


@app.route('/scouting/fire/<int:scout_id>', methods=['POST'])
@require_game
def scouting_fire(scout_id):
    gs = get_game_state()
    ok, msg = scouting_mod.fire_scout(gs, scout_id)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('scouting'))


@app.route('/scouting/assign-region', methods=['POST'])
@require_game
def scouting_assign_region():
    gs = get_game_state()
    ok, msg = scouting_mod.assign_scout_to_region(
        gs, int(request.form['scout_id']), request.form.get('region', ''))
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('scouting'))


@app.route('/scouting/assign-player', methods=['POST'])
@require_game
def scouting_assign_player():
    gs = get_game_state()
    ok, msg = scouting_mod.assign_scout_to_player(
        gs, int(request.form['scout_id']), int(request.form['player_id']))
    flash(msg, 'success' if ok else 'error')
    return redirect(request.referrer or url_for('scouting'))


@app.route('/scouting/unassign/<int:scout_id>', methods=['POST'])
@require_game
def scouting_unassign(scout_id):
    gs = get_game_state()
    ok, msg = scouting_mod.unassign_scout(gs, scout_id)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('scouting'))


@app.route('/scouting/shortlist/<int:player_id>', methods=['POST'])
@require_game
def scouting_shortlist(player_id):
    gs = get_game_state()
    ok, msg = scouting_mod.toggle_shortlist(gs, player_id)
    flash(msg, 'success' if ok else 'error')
    return redirect(request.referrer or url_for('scouting'))


# ---------------------------------------------------------------------------
# Routes: commercial

@app.route('/commercial')
@require_game
def commercial():
    gs = get_game_state()
    summary = commercial_mod.get_summary(gs)
    offers = commercial_mod.get_available_offers(gs)
    fan_news = NewsItem.query.filter_by(
        game_state_id=gs.id, category='fan'
    ).order_by(NewsItem.id.desc()).limit(6).all()
    return render_template('commercial.html', gs=gs, club=gs.managed_club,
                           summary=summary, offers=offers,
                           training_labels=commercial_mod.TRAINING_LABELS,
                           training_costs=commercial_mod.TRAINING_UPGRADE_COST,
                           fan_news=fan_news)


@app.route('/commercial/tickets', methods=['POST'])
@require_game
def commercial_tickets():
    gs = get_game_state()
    try:
        std = int(request.form.get('std_price', 25))
        prem = int(request.form.get('premium_price', 45))
    except ValueError:
        flash('Invalid price values.', 'error')
        return redirect(url_for('commercial'))
    ok, msg = commercial_mod.set_ticket_prices(gs, std, prem)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('commercial'))


@app.route('/commercial/expand', methods=['POST'])
@require_game
def commercial_expand():
    gs = get_game_state()
    try:
        seats = int(request.form.get('seats', 5000))
    except ValueError:
        seats = 5000
    ok, msg = commercial_mod.start_expansion(gs, seats)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('commercial'))


@app.route('/commercial/quality', methods=['POST'])
@require_game
def commercial_quality():
    gs = get_game_state()
    ok, msg = commercial_mod.upgrade_quality(gs)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('commercial'))


@app.route('/commercial/training', methods=['POST'])
@require_game
def commercial_training():
    gs = get_game_state()
    ok, msg = commercial_mod.upgrade_training(gs)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('commercial'))


@app.route('/commercial/sponsor', methods=['POST'])
@require_game
def commercial_sponsor():
    gs = get_game_state()
    deal_type = request.form.get('deal_type', '')
    company = request.form.get('company', '')
    try:
        value = int(request.form.get('annual_value', 0))
        years = int(request.form.get('years', 3))
    except ValueError:
        flash('Invalid deal values.', 'error')
        return redirect(url_for('commercial'))
    ok, msg = commercial_mod.accept_sponsor(gs, deal_type, company, value, years)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('commercial'))


# ---------------------------------------------------------------------------
# Routes: Youth Academy
# ---------------------------------------------------------------------------

@app.route('/academy')
@require_game
def academy():
    gs = get_game_state()
    youth = academy_mod.get_youth_squad(gs)
    aq = gs.managed_club.academy_quality or 2
    upgrade_cost = academy_mod.ACADEMY_UPGRADE_COST.get(aq)
    recs = {p.id: academy_mod.get_coach_youth_recommendation(gs, p) for p in youth}
    return render_template('academy.html', gs=gs, youth=youth,
                           aq=aq, upgrade_cost=upgrade_cost,
                           academy_labels=academy_mod.ACADEMY_LABELS, recs=recs,
                           stars=scouting_mod.stars)


@app.route('/academy/promote/<int:player_id>', methods=['POST'])
@require_game
def academy_promote(player_id):
    gs = get_game_state()
    ok, msg = academy_mod.promote_to_first_team(gs, player_id)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('academy'))


@app.route('/academy/release/<int:player_id>', methods=['POST'])
@require_game
def academy_release(player_id):
    gs = get_game_state()
    ok, msg = academy_mod.release_youth(gs, player_id)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('academy'))


@app.route('/academy/upgrade', methods=['POST'])
@require_game
def academy_upgrade():
    gs = get_game_state()
    ok, msg = academy_mod.upgrade_academy(gs)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('academy'))


# ---------------------------------------------------------------------------
# Routes: Squad Review (end of season)
# ---------------------------------------------------------------------------

@app.route('/squad-review')
@require_game
def squad_review():
    gs = get_game_state()
    season = gs.current_season
    mc = gs.managed_club
    mgr = mc.head_coach

    players = (Player.query
               .filter_by(club_id=mc.id, is_youth=False)
               .order_by(Player.position, Player.current_ability.desc())
               .all())

    # Gather season stats
    stats_map = {}
    for ps in PlayerStat.query.filter_by(season_id=season.id, club_id=mc.id).all():
        stats_map[ps.player_id] = ps

    # Coach recommendation per player
    def coach_rec(p):
        ps = stats_map.get(p.id)
        apps = ps.appearances if ps else 0
        if apps >= 25:
            return ('keep', 'Regular starter — keep')
        if apps >= 12:
            return ('neutral', 'Useful squad member')
        if p.age <= 21:
            return ('loan', 'Young — consider a loan')
        if p.age >= 32:
            return ('sell', 'Ageing — consider selling')
        return ('sell', 'Low minutes — sell or release')

    new_year = season.year + 1
    expiring = [p for p in players if p.contract_end <= new_year]
    watch    = [p for p in players if new_year < p.contract_end <= new_year + 1]
    secure   = [p for p in players if p.contract_end > new_year + 1]

    from game.commercial import get_wage_bill
    wage_bill = get_wage_bill(mc)
    wage_cap = gs.wage_cap_weekly or 0

    return render_template('squad_review.html',
                           gs=gs, season=season, mc=mc, mgr=mgr,
                           expiring=expiring, watch=watch, secure=secure,
                           stats_map=stats_map, coach_rec=coach_rec,
                           new_year=new_year,
                           wage_bill=wage_bill, wage_cap=wage_cap)


@app.route('/squad-review/action', methods=['POST'])
@require_game
def squad_review_action():
    gs = get_game_state()
    action = request.form.get('action')
    player_id = int(request.form.get('player_id', 0))
    p = Player.query.get(player_id)
    if not p or p.club_id != gs.managed_club_id:
        flash('Player not found.', 'error')
        return redirect(url_for('squad_review'))

    if action == 'list':
        p.transfer_listed = True
        db.session.commit()
        flash(f'{p.name} listed for transfer.', 'success')
    elif action == 'unlist':
        p.transfer_listed = False
        db.session.commit()
        flash(f'{p.name} removed from transfer list.', 'success')
    elif action == 'release':
        if p.contract_end <= gs.current_season.year + 1:
            name = p.name
            p.club_id = None
            db.session.commit()
            flash(f'{name} released on a free transfer.', 'success')
        else:
            flash('Can only release players whose contracts are expiring.', 'error')
    return redirect(url_for('squad_review'))


@app.route('/transfers/accept-counter/<int:bid_id>', methods=['POST'])
@require_game
def transfer_accept_counter(bid_id):
    gs = get_game_state()
    bid = TransferBid.query.get(bid_id)
    player = Player.query.get(bid.player_id) if bid else None
    ok, msg = transfers_mod.accept_counter_bid(gs, bid_id)
    flash(msg, 'success' if ok else 'error')
    if ok and player:
        demands_mod.on_player_signed(gs, player.position)
        auto_pick_lineup(gs)
    return redirect(url_for('transfers'))


@app.route('/transfers/decline-counter/<int:bid_id>', methods=['POST'])
@require_game
def transfer_decline_counter(bid_id):
    gs = get_game_state()
    ok, msg = transfers_mod.decline_counter_bid(gs, bid_id)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('transfers'))


@app.route('/transfers/incoming/accept/<int:bid_id>', methods=['POST'])
@require_game
def incoming_bid_accept(bid_id):
    gs = get_game_state()
    bid = IncomingBid.query.get(bid_id)
    player_was_listed = bid.player.transfer_listed if bid and bid.player else False
    ok, msg = transfers_mod.accept_incoming_bid(gs, bid_id)
    flash(msg, 'success' if ok else 'error')
    if ok:
        if player_was_listed:
            demands_mod.on_player_sold(gs)
        auto_pick_lineup(gs)
    return redirect(url_for('transfers', tab='inbox'))


@app.route('/transfers/incoming/reject/<int:bid_id>', methods=['POST'])
@require_game
def incoming_bid_reject(bid_id):
    gs = get_game_state()
    ok, msg = transfers_mod.reject_incoming_bid(gs, bid_id)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('transfers', tab='inbox'))


@app.route('/transfers/incoming/counter/<int:bid_id>', methods=['POST'])
@require_game
def incoming_bid_counter(bid_id):
    gs = get_game_state()
    try:
        counter_fee = int(request.form.get('counter_fee', 0))
    except (ValueError, TypeError):
        flash('Invalid counter-offer amount.', 'error')
        return redirect(url_for('transfers', tab='inbox'))
    bid = IncomingBid.query.get(bid_id)
    player_was_listed = bid.player.transfer_listed if bid and bid.player else False
    ok, msg = transfers_mod.counter_incoming_bid(gs, bid_id, counter_fee)
    flash(msg, 'success' if ok else 'error')
    if ok:
        if player_was_listed:
            demands_mod.on_player_sold(gs)
        auto_pick_lineup(gs)
    return redirect(url_for('transfers', tab='inbox'))


@app.route('/transfers/request/grant/<int:req_id>', methods=['POST'])
@require_game
def transfer_request_grant(req_id):
    gs = get_game_state()
    ok, msg = transfers_mod.grant_transfer_request(gs, req_id)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('transfers', tab='inbox'))


@app.route('/transfers/request/deny/<int:req_id>', methods=['POST'])
@require_game
def transfer_request_deny(req_id):
    gs = get_game_state()
    ok, msg = transfers_mod.deny_transfer_request(gs, req_id)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('transfers', tab='inbox'))


# ---------------------------------------------------------------------------
# Routes: match / advance
# ---------------------------------------------------------------------------

@app.route('/match/next')
@require_game
def next_match_preview():
    gs = get_game_state()
    if gs.is_sacked:
        return redirect(url_for('sacked'))
    # Allow European matches to be played even after the league season ends
    league_done = season_mod.is_league_season_over(gs)
    match = get_next_any_match(gs)
    if league_done and not match:
        return redirect(url_for('season_end'))
    if not match:
        return redirect(url_for('season_end'))
    home, away = match.home_club, match.away_club
    home_table = next((s for s in season_mod.get_league_table(
        gs.current_season_id, home.league_id) if s.club_id == home.id), None)
    away_table = next((s for s in season_mod.get_league_table(
        gs.current_season_id, away.league_id) if s.club_id == away.id), None)
    home_form = season_mod.get_club_form(home.id, gs.current_season_id, 5)
    away_form = season_mod.get_club_form(away.id, gs.current_season_id, 5)
    return render_template('match_preview.html', match=match, home=home,
                           away=away, home_table=home_table,
                           away_table=away_table,
                           home_form=home_form, away_form=away_form)


@app.route('/press/pre-match/<int:match_id>', methods=['GET', 'POST'])
@require_game
def press_pre_match(match_id):
    gs    = get_game_state()
    match = Match.query.get_or_404(match_id)
    if match.played:
        return redirect(url_for('match_result', match_id=match_id))

    if request.method == 'POST':
        q_id       = request.form.get('q_id', '')
        answer_key = request.form.get('answer_key', '')
        question   = press_mod.get_question_by_id(q_id)
        if question and answer_key:
            answer = press_mod.apply_pre_match_answer(gs, question, answer_key)
            if answer:
                flash(answer['flavour'], 'success')
        return redirect(url_for('play_match', match_id=match_id))

    question, _ = press_mod.get_pre_match_question(gs, match)
    opp = (match.away_club if match.home_club_id == gs.managed_club_id
           else match.home_club)
    return render_template('press_conference.html', match=match, opp=opp,
                           question=question, gs=gs)


@app.route('/match/play/<int:match_id>')
@require_game
def play_match(match_id):
    import random as _rnd
    gs = get_game_state()
    if gs.is_sacked:
        return redirect(url_for('sacked'))

    match = Match.query.get_or_404(match_id)
    if match.played:
        return redirect(url_for('match_result', match_id=match_id))

    season = gs.current_season
    comp   = match.competition or 'League'
    is_cup = 'Cup' in comp
    is_cl_group = comp in europe_mod.CL_GROUPS
    is_euro_ko  = comp in (europe_mod._CL_KO_NAMES + europe_mod._UEFA_NAMES)
    is_league   = not is_cup and not is_cl_group and not is_euro_ko
    league = League.query.get(match.league_id) if match.league_id else gs.managed_club.league

    home_score, away_score, events, commentary, stats, participants = engine.simulate_match(
        match.home_club, match.away_club, season, match, gs)

    # Cup and knockout European matches must produce a winner
    if (is_cup or is_euro_ko) and home_score == away_score:
        if _rnd.random() < 0.5:
            home_score += 1
        else:
            away_score += 1

    match.home_score = home_score
    match.away_score = away_score
    match.played = True
    for ev in events:
        me = MatchEvent(match_id=match.id, minute=ev['minute'],
                        event_type=ev['type'], player_id=ev.get('player_id'),
                        assist_player_id=ev.get('assist_player_id'),
                        club_id=ev.get('club_id'),
                        description=ev.get('description', ''))
        db.session.add(me)
    db.session.commit()

    if is_league:
        season_mod.update_standings(season, league, match.home_club_id,
                                    match.away_club_id, home_score, away_score)
    engine.update_player_stats(events, season.id)
    engine.record_participation(participants, season.id, match.id)

    # Discipline
    injuries_mod.process_match_discipline(events, season.id, gs)

    # Simulate rest of that league match-day
    if is_league:
        season_mod.simulate_other_matches(season, league, match.match_date, gs, app)

    # Simulate AI cup and European matches
    cups_mod.simulate_cup_day(season, match.match_date, gs)
    europe_mod.simulate_europe_day(season, match.match_date, gs)

    # ----- Morale update -----
    mc      = gs.managed_club
    we_home = match.home_club_id == mc.id
    our_score   = home_score if we_home else away_score
    their_score = away_score if we_home else home_score

    starter_ids = [l.player_id for l in
                   Lineup.query.filter(Lineup.game_state_id == gs.id,
                                       Lineup.slot <= 11).all()]
    sub_ids     = [l.player_id for l in
                   Lineup.query.filter(Lineup.game_state_id == gs.id,
                                       Lineup.slot > 11).all()]
    scorer_ids   = [ev['player_id'] for ev in events
                    if ev['type'] == 'goal' and ev.get('club_id') == mc.id
                    and ev.get('player_id')]
    assister_ids = [ev['assist_player_id'] for ev in events
                    if ev['type'] == 'goal' and ev.get('club_id') == mc.id
                    and ev.get('assist_player_id')]
    apply_match_morale(gs, our_score, their_score,
                       starter_ids, sub_ids, scorer_ids, assister_ids)

    # ----- Manager satisfaction -----
    if our_score > their_score:
        staff_mod.update_manager_satisfaction(gs, 'win')
    elif our_score == their_score:
        staff_mod.update_manager_satisfaction(gs, 'draw')
    else:
        staff_mod.update_manager_satisfaction(gs, 'loss')

    # Refresh lineup for next match using manager's preferred formation
    auto_pick_lineup(gs)

    # ----- Board confidence (league matches only) -----
    sacked = False
    if is_league:
        table    = season_mod.get_league_table(gs.current_season_id, mc.league_id)
        position = next((i + 1 for i, s in enumerate(table)
                         if s.club_id == mc.id), len(table))
        result   = ('W' if our_score > their_score else
                    'D' if our_score == their_score else 'L')
        sacked = update_board_after_match(gs, result, position)

    # Advance injuries
    injuries_mod.advance_injuries()

    # Post-match injury check
    starters, _ = engine.get_squad_for_match(gs.managed_club, gs)
    injuries_mod.check_match_injuries(starters, gs)

    # Reduce suspensions
    injuries_mod.reduce_suspensions()

    # Advance date
    gs.current_date = match.match_date

    # Post-match news
    opp = match.away_club if we_home else match.home_club
    verdict = ('win' if our_score > their_score else
               'draw' if our_score == their_score else 'defeat')
    headline = (f"{mc.short_name} {home_score}-{away_score} {opp.short_name}"
                if we_home else
                f"{opp.short_name} {home_score}-{away_score} {mc.short_name}")
    season_mod.add_news(gs, f"[{comp}] {headline}",
                        f"A {verdict} for {mc.name} against {opp.name}.",
                        category='result')

    transfers_mod.ai_transfers(gs, gs.current_date)

    # Chairman demands: check expiry then maybe issue a new one
    demands_mod.check_active_demands(gs)
    demands_mod.maybe_generate_demand(gs)

    # Contract negotiations: agent approaches and expiry checks
    contracts_mod.maybe_agent_approach(gs)
    contracts_mod.expire_old_negotiations(gs)

    # Scouting: progress assignments and region scouring
    scouting_mod.process_scouting(gs)

    # Commercial: matchday revenue, fan mood, stadium expansion check
    commercial_mod.calculate_matchday_revenue(gs, match)
    if our_score > their_score:
        commercial_mod.update_fan_happiness(gs, 'win')
    elif our_score == their_score:
        commercial_mod.update_fan_happiness(gs, 'draw')
    elif their_score - our_score >= 3:
        commercial_mod.update_fan_happiness(gs, 'heavy_loss')
    else:
        commercial_mod.update_fan_happiness(gs, 'loss')
    commercial_mod.check_expansion_complete(gs)
    commercial_mod.maybe_fan_forum_post(gs, our_score, their_score)
    if we_home:
        commercial_mod.tick_ticket_happiness(gs)

    # Ongoing head-coach feedback to the DoF (occasional)
    staff_mod.maybe_coach_feedback(gs)

    # Post-match media reaction
    press_mod.generate_post_match_headline(gs, our_score, their_score, opp, comp)

    # Players pushing for transfers or contract talks
    transfers_mod.maybe_player_transfer_request(gs)

    # Possibly schedule a DoF–Manager meeting
    staff_mod.maybe_schedule_meeting(gs)

    # Check if manager wants to resign after this result
    manager_resigned = staff_mod.check_manager_status(gs)

    if sacked:
        gs.is_sacked = True
    db.session.commit()

    if sacked:
        return redirect(url_for('sacked'))

    if manager_resigned:
        flash(f'The head coach has resigned. Appoint a new manager from the Staff page.', 'error')

    return redirect(url_for('match_view', match_id=match.id))


@app.route('/match/view/<int:match_id>')
@require_game
def match_view(match_id):
    """Animated commentary replay (re-simulated display is stored client-side
    via events)."""
    gs = get_game_state()
    match = Match.query.get_or_404(match_id)
    events = sorted(match.events, key=lambda e: e.minute)
    return render_template('match_live.html', match=match, events=events,
                           managed_club_id=gs.managed_club_id)


@app.route('/match/result/<int:match_id>')
@require_game
def match_result(match_id):
    gs = get_game_state()
    match = Match.query.get_or_404(match_id)
    events = sorted(match.events, key=lambda e: e.minute)

    league = League.query.get(match.league_id) if match.league_id else None
    if league:
        table  = season_mod.get_league_table(gs.current_season_id, league.id)
        others = Match.query.filter_by(
            season_id=gs.current_season_id, league_id=league.id,
            match_date=match.match_date, played=True).filter(
            Match.id != match.id).all()
    else:
        table  = []
        # For European/cup matches show other matches from the same round
        if match.competition:
            others = Match.query.filter_by(
                season_id=gs.current_season_id,
                competition=match.competition,
                match_date=match.match_date,
                played=True).filter(Match.id != match.id).all()
        else:
            others = []

    group_standings = None
    if match.competition and 'CL Group' in match.competition:
        group_standings = europe_mod.get_group_standings(
            gs.current_season_id, match.competition)

    ratings = MatchRating.query.filter_by(match_id=match.id).all()
    home_ratings = sorted([r for r in ratings if r.club_id == match.home_club_id],
                          key=lambda r: r.rating, reverse=True)
    away_ratings = sorted([r for r in ratings if r.club_id == match.away_club_id],
                          key=lambda r: r.rating, reverse=True)

    return render_template('match_result.html', match=match, events=events,
                           table=table, others=others,
                           group_standings=group_standings,
                           managed_club_id=gs.managed_club_id,
                           home_ratings=home_ratings, away_ratings=away_ratings)


# ---------------------------------------------------------------------------
# Routes: league table / fixtures
# ---------------------------------------------------------------------------

@app.route('/table')
@app.route('/table/<int:league_id>')
@require_game
def league_table(league_id=None):
    gs = get_game_state()
    if league_id is None:
        league_id = gs.managed_club.league_id
    league = League.query.get_or_404(league_id)
    table = season_mod.get_league_table(gs.current_season_id, league_id)
    all_leagues = League.query.all()
    return render_template('table.html', league=league, table=table,
                           all_leagues=all_leagues,
                           managed_club_id=gs.managed_club_id)


@app.route('/fixtures')
@require_game
def fixtures():
    gs = get_game_state()
    club = gs.managed_club
    matches = Match.query.filter(
        Match.season_id == gs.current_season_id,
        (Match.home_club_id == club.id) | (Match.away_club_id == club.id)
    ).order_by(Match.match_date).all()
    return render_template('fixtures.html', club=club, matches=matches)


# ---------------------------------------------------------------------------
# Routes: transfers
# ---------------------------------------------------------------------------

@app.route('/transfers')
@require_game
def transfers():
    gs = get_game_state()
    club = gs.managed_club
    tab = request.args.get('tab', 'buy')
    query = request.args.get('q', '')
    position = request.args.get('position', 'All')
    max_value = request.args.get('max_value', '')
    max_value_int = int(max_value) if max_value.isdigit() else 999999999

    results = []
    free_agents = []
    loan_candidates = []
    loaned_out = []

    if tab == 'buy':
        if query or position != 'All' or max_value:
            players = transfers_mod.search_players(
                query=query, position=position, max_value=max_value_int,
                exclude_club_id=club.id, buying_club=club)
        else:
            players = transfers_mod.get_transfer_listed(
                exclude_club_id=club.id, position=position)
        results = [(p, transfers_mod.get_transfer_value(p)) for p in players]
    elif tab == 'loan':
        if query or position != 'All':
            players = transfers_mod.search_players(
                query=query, position=position, exclude_club_id=club.id,
                buying_club=club)
        else:
            players = transfers_mod.search_players(
                position=position, exclude_club_id=club.id, buying_club=club)
        results = [(p, transfers_mod.get_transfer_value(p)) for p in players]
    elif tab == 'free-agents':
        free_agents = transfers_mod.get_free_agents(position=position)
    elif tab == 'loan-out':
        loaned_out = transfers_mod.get_loaned_out(gs)
        loaned_out_ids = {ln.player_id for ln in loaned_out}
        loan_candidates = [
            p for p in club.players
            if not p.is_youth and p.id not in loaned_out_ids
        ]
        loan_candidates.sort(key=lambda p: p.age)

    active_loans = Loan.query.filter_by(
        loan_club_id=club.id, season_id=gs.current_season_id,
        active=True).all()

    window_open, window_msg, _ = transfers_mod.is_window_open(gs.current_date)
    wage_bill = transfers_mod.get_wage_bill(club)
    pending_bids = transfers_mod.get_pending_bids(gs)
    incoming_bids = transfers_mod.get_incoming_bids(gs)
    transfer_requests = transfers_mod.get_transfer_requests(gs)

    return render_template('transfers.html', club=club, results=results,
                           query=query, position=position, max_value=max_value,
                           tab=tab, active_loans=active_loans,
                           free_agents=free_agents, loan_candidates=loan_candidates,
                           loaned_out=loaned_out,
                           window_open=window_open, window_msg=window_msg,
                           wage_bill=wage_bill, pending_bids=pending_bids,
                           incoming_bids=incoming_bids,
                           transfer_requests=transfer_requests)


@app.route('/transfers/offer', methods=['POST'])
@require_game
def transfer_offer():
    gs = get_game_state()
    player_id = int(request.form.get('player_id'))
    offer = int(request.form.get('offer', 0))
    player = Player.query.get(player_id)
    # Enforce transfer window — free agents (no club) are always signable
    if player and player.club_id is not None:
        window_open, window_msg, _ = transfers_mod.is_window_open(gs.current_date)
        if not window_open:
            flash(f'Transfer window is closed. {window_msg}', 'error')
            return redirect(request.referrer or url_for('transfers'))
    ok, msg = transfers_mod.make_offer(gs, player_id, offer)
    flash(msg, 'success' if ok else 'error')
    if ok and player:
        demands_mod.on_player_signed(gs, player.position)
        auto_pick_lineup(gs)
    return redirect(request.referrer or url_for('transfers'))


@app.route('/transfers/list/<int:player_id>', methods=['POST'])
@require_game
def transfer_list(player_id):
    gs = get_game_state()
    ok, msg = transfers_mod.list_player_for_sale(gs, player_id)
    flash(msg, 'success' if ok else 'error')
    return redirect(request.referrer or url_for('squad'))


@app.route('/transfers/release/<int:player_id>', methods=['POST'])
@require_game
def transfer_release(player_id):
    gs = get_game_state()
    player = Player.query.get(player_id)
    was_listed = player.transfer_listed if player else False
    ok, msg = transfers_mod.release_player(gs, player_id)
    flash(msg, 'success' if ok else 'error')
    if ok:
        if was_listed:
            demands_mod.on_player_sold(gs)
        auto_pick_lineup(gs)
    return redirect(url_for('squad'))


@app.route('/transfers/loan/<int:player_id>', methods=['POST'])
@require_game
def transfer_loan(player_id):
    gs = get_game_state()
    window_open, window_msg, _ = transfers_mod.is_window_open(gs.current_date)
    if not window_open:
        flash(f'Transfer window is closed. {window_msg}', 'error')
        return redirect(request.referrer or url_for('transfers'))
    ok, msg = transfers_mod.loan_player(gs, player_id)
    flash(msg, 'success' if ok else 'error')
    if ok:
        auto_pick_lineup(gs)
    return redirect(request.referrer or url_for('transfers'))


@app.route('/transfers/sign-free-agent', methods=['POST'])
@require_game
def transfer_sign_free_agent():
    gs = get_game_state()
    player_id = int(request.form.get('player_id'))
    try:
        wage = int(request.form.get('wage', 0))
        years = int(request.form.get('years', 2))
    except (ValueError, TypeError):
        flash('Invalid wage or contract length.', 'error')
        return redirect(url_for('transfers', tab='free-agents'))
    ok, msg = transfers_mod.sign_free_agent(gs, player_id, wage, years)
    flash(msg, 'success' if ok else 'error')
    if ok:
        demands_mod.on_player_signed(gs, Player.query.get(player_id).position if Player.query.get(player_id) else 'any')
        auto_pick_lineup(gs)
    return redirect(url_for('transfers', tab='free-agents'))


@app.route('/transfers/loan-out/<int:player_id>', methods=['POST'])
@require_game
def transfer_loan_out(player_id):
    gs = get_game_state()
    window_open, window_msg, _ = transfers_mod.is_window_open(gs.current_date)
    if not window_open:
        flash(f'Transfer window is closed. {window_msg}', 'error')
        return redirect(url_for('transfers', tab='loan-out'))
    ok, msg = transfers_mod.loan_out_player(gs, player_id)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('transfers', tab='loan-out'))


@app.route('/transfers/recall-loan/<int:loan_id>', methods=['POST'])
@require_game
def transfer_recall_loan(loan_id):
    gs = get_game_state()
    ok, msg = transfers_mod.recall_loan(gs, loan_id)
    flash(msg, 'success' if ok else 'error')
    if ok:
        auto_pick_lineup(gs)
    return redirect(url_for('transfers', tab='loan-out'))


@app.route('/contract/offer/<int:player_id>', methods=['POST'])
@require_game
def contract_offer(player_id):
    gs = get_game_state()
    ok, msg = transfers_mod.offer_contract(gs, player_id)
    flash(msg, 'success' if ok else 'error')
    return redirect(url_for('player_detail', player_id=player_id))


# ---------------------------------------------------------------------------
# Routes: news
# ---------------------------------------------------------------------------

@app.route('/news')
@require_game
def news():
    gs = get_game_state()
    items = NewsItem.query.filter_by(game_state_id=gs.id).order_by(
        NewsItem.id.desc()).all()
    # mark all read
    for it in items:
        it.read = True
    db.session.commit()
    return render_template('news.html', items=items)


# ---------------------------------------------------------------------------
# Routes: stats
# ---------------------------------------------------------------------------

@app.route('/stats')
@require_game
def stats():
    gs = get_game_state()
    top_scorers = db.session.query(PlayerStat).filter_by(
        season_id=gs.current_season_id).order_by(
        PlayerStat.goals.desc()).limit(20).all()
    top_assists = db.session.query(PlayerStat).filter_by(
        season_id=gs.current_season_id).order_by(
        PlayerStat.assists.desc()).limit(20).all()
    top_appearances = db.session.query(PlayerStat).filter_by(
        season_id=gs.current_season_id).order_by(
        PlayerStat.appearances.desc()).limit(20).all()
    top_cards = db.session.query(PlayerStat).filter_by(
        season_id=gs.current_season_id).filter(
        (PlayerStat.yellow_cards > 0) | (PlayerStat.red_cards > 0)).order_by(
        (PlayerStat.yellow_cards + PlayerStat.red_cards * 3).desc()).limit(15).all()
    # Top rated (min 5 apps) — avg_rating is computed, so sort in Python
    rated = db.session.query(PlayerStat).filter(
        PlayerStat.season_id == gs.current_season_id,
        PlayerStat.appearances >= 5,
        PlayerStat.total_rating > 0).all()
    top_rated = sorted(rated, key=lambda p: p.total_rating / p.appearances,
                       reverse=True)[:20]
    # My squad stats
    my_stats = db.session.query(PlayerStat).filter_by(
        season_id=gs.current_season_id,
        club_id=gs.managed_club_id).order_by(
        PlayerStat.appearances.desc()).all()
    return render_template('stats.html',
                           top_scorers=top_scorers, top_assists=top_assists,
                           top_appearances=top_appearances, top_cards=top_cards,
                           top_rated=top_rated,
                           my_stats=my_stats, club=gs.managed_club)


@app.route('/records')
@require_game
def club_records():
    gs = get_game_state()
    recs = records_mod.get_club_records(gs)
    awards = records_mod.get_season_awards(gs)
    return render_template('records.html', records=recs, awards=awards,
                           club=gs.managed_club, season=gs.current_season, gs=gs)


# ---------------------------------------------------------------------------
# Routes: season end
# ---------------------------------------------------------------------------

@app.route('/season-end')
@require_game
def season_end():
    gs = get_game_state()
    season = gs.current_season
    league = gs.managed_club.league
    table = season_mod.get_league_table(season.id, league.id)
    mc = gs.managed_club
    position = next((i + 1 for i, s in enumerate(table) if s.club_id == mc.id), 0)
    relegated = [s.club for s in table[-3:]] if len(table) >= 20 else []
    top_scorers = (PlayerStat.query.filter_by(season_id=season.id)
                   .order_by(PlayerStat.goals.desc()).limit(10).all())
    board_met = (position <= (gs.board_max_pos or 17)) if position else False

    # European final winners this season
    cl_winner = None
    cl_final = Match.query.filter_by(season_id=season.id,
                                     competition='CL Final', played=True).first()
    if cl_final:
        cl_winner = (cl_final.home_club if (cl_final.home_score or 0) >= (cl_final.away_score or 0)
                     else cl_final.away_club)
    uefa_winner = None
    uefa_final = Match.query.filter_by(season_id=season.id,
                                       competition='UEFA Final', played=True).first()
    if uefa_final:
        uefa_winner = (uefa_final.home_club if (uefa_final.home_score or 0) >= (uefa_final.away_score or 0)
                       else uefa_final.away_club)

    prize_money = commercial_mod.calculate_prize_money(position, league.level or 1) if position else 0
    awards = records_mod.get_season_awards(gs)
    return render_template('season_end.html', table=table, mc=mc, position=position,
                           relegated=relegated, season=season, top_scorers=top_scorers,
                           board_met=board_met, cl_winner=cl_winner, uefa_winner=uefa_winner,
                           gs=gs, prize_money=prize_money, awards=awards)


@app.route('/season-end/advance', methods=['POST'])
@require_game
def advance_season():
    gs = get_game_state()
    # Pay prize money before rolling over (position is from completed season)
    season = gs.current_season
    league = gs.managed_club.league
    table = season_mod.get_league_table(season.id, league.id)
    mc = gs.managed_club
    position = next((i + 1 for i, s in enumerate(table) if s.club_id == mc.id), len(table))
    commercial_mod.pay_prize_money(gs, position, league.level or 1)

    # Season awards news before rolling over
    records_mod.post_season_awards_news(gs)

    transfers_mod.return_loaned_out(gs)   # return any players you loaned out
    season_mod.process_new_season(gs)
    commercial_mod.process_season_sponsors(gs)
    gs.season_revenue = 0   # reset annual counter
    db.session.commit()
    flash(f'Welcome to season {gs.current_season.name}!', 'success')
    return redirect(url_for('dashboard'))


# ---------------------------------------------------------------------------
# Routes: cup fixtures
# ---------------------------------------------------------------------------

@app.route('/cups')
@require_game
def cup_fixtures():
    gs = get_game_state()
    fa = cups_mod.get_cup_matches_for_club(gs.managed_club_id, gs.current_season_id)
    fa_all = [m for m in fa if 'FA Cup' in m.competition]
    lc_all = [m for m in fa if 'League Cup' in m.competition]
    return render_template('cups.html', fa_matches=fa_all, lc_matches=lc_all,
                           managed_club_id=gs.managed_club_id)


# ---------------------------------------------------------------------------
# Routes: European competition
# ---------------------------------------------------------------------------

@app.route('/europe')
@require_game
def europe():
    gs = get_game_state()
    all_euro = europe_mod.get_euro_matches_for_club(
        gs.managed_club_id, gs.current_season_id)
    cl_matches   = [m for m in all_euro if 'CL' in m.competition]
    uefa_matches = [m for m in all_euro if 'UEFA' in m.competition]

    our_group     = europe_mod.get_our_cl_group(gs.managed_club_id, gs.current_season_id)
    group_standings = (europe_mod.get_group_standings(gs.current_season_id, our_group)
                       if our_group else None)
    in_europe = bool(all_euro)

    return render_template('europe.html',
                           cl_matches=cl_matches,
                           uefa_matches=uefa_matches,
                           group_standings=group_standings,
                           our_group=our_group,
                           managed_club_id=gs.managed_club_id,
                           in_europe=in_europe)


# ---------------------------------------------------------------------------
# Routes: board room
# ---------------------------------------------------------------------------

@app.route('/board')
@require_game
def board():
    gs = get_game_state()
    league   = gs.managed_club.league
    table    = season_mod.get_league_table(gs.current_season_id, league.id)
    position = next((i + 1 for i, s in enumerate(table)
                     if s.club_id == gs.managed_club_id), 0)
    board_news = NewsItem.query.filter_by(
        game_state_id=gs.id, category='board').order_by(
        NewsItem.id.desc()).limit(5).all()
    active_demands = demands_mod.get_active_demands(gs)
    return render_template('board.html', gs=gs, position=position,
                           board_news=board_news, total_teams=len(table),
                           active_demands=active_demands)


# ---------------------------------------------------------------------------
# Routes: sacked
# ---------------------------------------------------------------------------

@app.route('/sacked')
def sacked():
    gs = get_game_state()
    return render_template('sacked.html', gs=gs)


# ---------------------------------------------------------------------------
# CLI / bootstrap
# ---------------------------------------------------------------------------

@app.cli.command('init-db')
def init_db_command():
    db.create_all()
    seed_database()
    print('Database initialised and seeded.')


def _migrate_db():
    """Add any missing columns to existing tables (safe to run repeatedly)."""
    try:
        conn = db.engine.raw_connection()
        cursor = conn.cursor()

        def _add_missing(table, migrations):
            cursor.execute(f'PRAGMA table_info({table})')
            cols = {row[1] for row in cursor.fetchall()}
            for col, sql in migrations:
                if col not in cols:
                    cursor.execute(sql)

        _add_missing('players', [
            ('agent_name',      "ALTER TABLE players ADD COLUMN agent_name VARCHAR(100) DEFAULT ''"),
            ('agent_aggression','ALTER TABLE players ADD COLUMN agent_aggression INTEGER DEFAULT 5'),
            ('release_clause',  'ALTER TABLE players ADD COLUMN release_clause INTEGER'),
        ])
        _add_missing('game_states', [
            ('fan_happiness',       'ALTER TABLE game_states ADD COLUMN fan_happiness INTEGER DEFAULT 65'),
            ('ticket_price_std',    'ALTER TABLE game_states ADD COLUMN ticket_price_std INTEGER DEFAULT 25'),
            ('ticket_price_premium','ALTER TABLE game_states ADD COLUMN ticket_price_premium INTEGER DEFAULT 45'),
            ('season_revenue',      'ALTER TABLE game_states ADD COLUMN season_revenue INTEGER DEFAULT 0'),
            ('wage_cap_weekly',     'ALTER TABLE game_states ADD COLUMN wage_cap_weekly INTEGER DEFAULT 0'),
        ])
        _add_missing('clubs', [
            ('training_level',  'ALTER TABLE clubs ADD COLUMN training_level INTEGER DEFAULT 2'),
            ('academy_quality', 'ALTER TABLE clubs ADD COLUMN academy_quality INTEGER DEFAULT 2'),
        ])
        _add_missing('player_stats', [
            ('total_rating', 'ALTER TABLE player_stats ADD COLUMN total_rating INTEGER DEFAULT 0'),
        ])
        _add_missing('matches', [
            ('attendance', 'ALTER TABLE matches ADD COLUMN attendance INTEGER'),
        ])
        # Create new tables if missing
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS match_ratings (
                id INTEGER PRIMARY KEY,
                match_id INTEGER REFERENCES matches(id),
                player_id INTEGER REFERENCES players(id),
                club_id INTEGER REFERENCES clubs(id),
                rating FLOAT DEFAULT 6.0,
                started BOOLEAN DEFAULT 1,
                goals INTEGER DEFAULT 0,
                assists INTEGER DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS incoming_bids (
                id INTEGER PRIMARY KEY,
                game_state_id INTEGER REFERENCES game_states(id),
                player_id INTEGER REFERENCES players(id),
                bidding_club_id INTEGER REFERENCES clubs(id),
                offered_fee INTEGER DEFAULT 0,
                counter_fee INTEGER,
                status VARCHAR(30) DEFAULT 'pending',
                created_date VARCHAR(20)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transfer_requests (
                id INTEGER PRIMARY KEY,
                game_state_id INTEGER REFERENCES game_states(id),
                player_id INTEGER REFERENCES players(id),
                reason VARCHAR(100) DEFAULT 'unhappy',
                created_date VARCHAR(20),
                status VARCHAR(20) DEFAULT 'pending'
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS manager_meetings (
                id INTEGER PRIMARY KEY,
                game_state_id INTEGER REFERENCES game_states(id),
                manager_id INTEGER REFERENCES managers(id),
                topic VARCHAR(30),
                scheduled_date VARCHAR(20),
                status VARCHAR(20) DEFAULT 'pending',
                resolved_choice VARCHAR(30)
            )
        """)
        conn.commit()
        conn.close()
    except Exception:
        pass


def bootstrap():
    with app.app_context():
        db.create_all()
        _migrate_db()
        try:
            seed_database()
        except Exception as e:
            print(f'Seed skipped/failed: {e}')


if __name__ == '__main__':
    bootstrap()
    app.run(debug=True, host='0.0.0.0', port=5000)
