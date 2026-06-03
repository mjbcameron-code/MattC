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
                         ContractNegotiation, TransferBid)
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
    return render_template('dashboard.html',
                           club=club, next_match=next_match, recent=recent,
                           table=table[:8], position=position, news=news,
                           squad_size=squad_size, injured=injured,
                           total_teams=len(table), avg_morale=avg_morale,
                           next_euro=next_euro, wage_bill=wage_bill)


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
    return render_template('player.html', player=player, stats=stats,
                           value=value, managed=player.club_id == gs.managed_club_id,
                           on_loan=on_loan)


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
    return render_template('staff.html',
                           head_coach=gs.managed_club.head_coach,
                           available=staff_mod.get_available_managers(),
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

    home_score, away_score, events, commentary, stats = engine.simulate_match(
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

    return render_template('match_result.html', match=match, events=events,
                           table=table, others=others,
                           group_standings=group_standings,
                           managed_club_id=gs.managed_club_id)


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
    if query or position != 'All' or max_value:
        results = transfers_mod.search_players(
            query=query, position=position, max_value=max_value_int,
            exclude_club_id=club.id)
        results = [(p, transfers_mod.get_transfer_value(p)) for p in results]

    active_loans = Loan.query.filter_by(
        loan_club_id=club.id, season_id=gs.current_season_id,
        active=True).all()

    window_open, window_msg, _ = transfers_mod.is_window_open(gs.current_date)
    wage_bill = transfers_mod.get_wage_bill(club)
    pending_bids = transfers_mod.get_pending_bids(gs)

    return render_template('transfers.html', club=club, results=results,
                           query=query, position=position, max_value=max_value,
                           tab=tab, active_loans=active_loans,
                           window_open=window_open, window_msg=window_msg,
                           wage_bill=wage_bill, pending_bids=pending_bids)


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
    # My squad stats
    my_stats = db.session.query(PlayerStat).filter_by(
        season_id=gs.current_season_id,
        club_id=gs.managed_club_id).order_by(
        PlayerStat.appearances.desc()).all()
    return render_template('stats.html',
                           top_scorers=top_scorers, top_assists=top_assists,
                           top_appearances=top_appearances, top_cards=top_cards,
                           my_stats=my_stats, club=gs.managed_club)


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

    return render_template('season_end.html', table=table, mc=mc, position=position,
                           relegated=relegated, season=season, top_scorers=top_scorers,
                           board_met=board_met, cl_winner=cl_winner, uefa_winner=uefa_winner,
                           gs=gs)


@app.route('/season-end/advance', methods=['POST'])
@require_game
def advance_season():
    gs = get_game_state()
    season_mod.process_new_season(gs)
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
        cursor.execute('PRAGMA table_info(players)')
        cols = [row[1] for row in cursor.fetchall()]
        migrations = [
            ('agent_name', "ALTER TABLE players ADD COLUMN agent_name VARCHAR(100) DEFAULT ''"),
            ('agent_aggression', 'ALTER TABLE players ADD COLUMN agent_aggression INTEGER DEFAULT 5'),
            ('release_clause', 'ALTER TABLE players ADD COLUMN release_clause INTEGER'),
        ]
        for col, sql in migrations:
            if col not in cols:
                cursor.execute(sql)
        conn.commit()
        conn.close()
    except Exception:
        pass


def bootstrap():
    with app.app_context():
        db.create_all()
        _migrate_db()
        if not database_is_seeded():
            try:
                seed_database()
                print('Database seeded with squad data.')
            except Exception as e:
                print(f'Seed skipped/failed: {e}')


if __name__ == '__main__':
    bootstrap()
    app.run(debug=True, host='0.0.0.0', port=5000)
