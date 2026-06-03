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
                         Lineup, Suspension, Loan)
from game.setup import (seed_database, new_game, auto_pick_lineup,
                       database_is_seeded)
from game import season as season_mod
from game import engine
from game import transfers as transfers_mod
from game import cups as cups_mod
from game import injuries as injuries_mod
from game import europe as europe_mod
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

    return render_template('dashboard.html',
                           club=club, next_match=next_match, recent=recent,
                           table=table[:8], position=position, news=news,
                           squad_size=squad_size, injured=injured,
                           total_teams=len(table), avg_morale=avg_morale,
                           next_euro=next_euro)


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

@app.route('/tactics', methods=['GET', 'POST'])
@require_game
def tactics():
    gs = get_game_state()
    club = gs.managed_club

    if request.method == 'POST':
        formation = request.form.get('formation', gs.formation)
        tactic = request.form.get('tactic', gs.tactic)
        gs.formation = formation
        gs.tactic = tactic
        db.session.commit()
        if request.form.get('auto') == '1':
            auto_pick_lineup(gs, formation)
        flash('Tactics updated.', 'success')
        return redirect(url_for('tactics'))

    lineups = Lineup.query.filter_by(game_state_id=gs.id).order_by(
        Lineup.slot).all()
    starters = [l for l in lineups if l.slot <= 11]
    subs = [l for l in lineups if l.slot > 11]
    all_players = Player.query.filter_by(club_id=club.id).all()
    return render_template('tactics.html', club=club, starters=starters,
                           subs=subs, all_players=all_players,
                           formation=gs.formation, tactic=gs.tactic)


@app.route('/tactics/set-player', methods=['POST'])
@require_game
def set_lineup_player():
    """Swap a player into a lineup slot (AJAX)."""
    gs = get_game_state()
    slot = int(request.form.get('slot'))
    player_id = int(request.form.get('player_id'))

    # If player already in another slot, swap
    existing = Lineup.query.filter_by(
        game_state_id=gs.id, player_id=player_id).first()
    target = Lineup.query.filter_by(game_state_id=gs.id, slot=slot).first()

    if existing and target and existing.id != target.id:
        existing.player_id, target.player_id = target.player_id, player_id
    elif target:
        target.player_id = player_id
    else:
        player = Player.query.get(player_id)
        lu = Lineup(game_state_id=gs.id, player_id=player_id, slot=slot,
                    position_played=player.position)
        db.session.add(lu)
    db.session.commit()
    return jsonify({'ok': True})


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

    if sacked:
        gs.is_sacked = True
    db.session.commit()

    if sacked:
        return redirect(url_for('sacked'))

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

    # Active loans at this club
    active_loans = Loan.query.filter_by(
        loan_club_id=club.id, season_id=gs.current_season_id,
        active=True).all()

    return render_template('transfers.html', club=club, results=results,
                           query=query, position=position, max_value=max_value,
                           tab=tab, active_loans=active_loans)


@app.route('/transfers/offer', methods=['POST'])
@require_game
def transfer_offer():
    gs = get_game_state()
    player_id = int(request.form.get('player_id'))
    offer = int(request.form.get('offer', 0))
    ok, msg = transfers_mod.make_offer(gs, player_id, offer)
    flash(msg, 'success' if ok else 'error')
    if ok:
        auto_pick_lineup(gs)  # refresh lineup with new signing if needed
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
    ok, msg = transfers_mod.release_player(gs, player_id)
    flash(msg, 'success' if ok else 'error')
    auto_pick_lineup(gs)
    return redirect(url_for('squad'))


@app.route('/transfers/loan/<int:player_id>', methods=['POST'])
@require_game
def transfer_loan(player_id):
    gs = get_game_state()
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
    return render_template('stats.html', top_scorers=top_scorers,
                           top_assists=top_assists)


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
    return render_template('season_end.html', table=table, mc=mc, position=position,
                           relegated=relegated, season=season, top_scorers=top_scorers)


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
    return render_template('board.html', gs=gs, position=position,
                           board_news=board_news,
                           total_teams=len(table))


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


def bootstrap():
    with app.app_context():
        db.create_all()
        if not database_is_seeded():
            try:
                seed_database()
                print('Database seeded with squad data.')
            except Exception as e:
                print(f'Seed skipped/failed: {e}')


if __name__ == '__main__':
    bootstrap()
    app.run(debug=True, host='0.0.0.0', port=5000)
