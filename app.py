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
                         Lineup)
from game.setup import (seed_database, new_game, auto_pick_lineup,
                       database_is_seeded)
from game import season as season_mod
from game import engine
from game import transfers as transfers_mod

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
    next_match = season_mod.get_next_match(gs)
    recent = season_mod.get_recent_results(gs)
    table = season_mod.get_league_table(gs.current_season_id, club.league_id)
    # find our position
    position = next((i + 1 for i, s in enumerate(table)
                     if s.club_id == club.id), None)
    news = NewsItem.query.filter_by(game_state_id=gs.id).order_by(
        NewsItem.id.desc()).limit(6).all()
    squad_size = Player.query.filter_by(club_id=club.id).count()
    injured = Player.query.filter_by(club_id=club.id, is_injured=True).count()

    return render_template('dashboard.html',
                           club=club, next_match=next_match, recent=recent,
                           table=table[:8], position=position, news=news,
                           squad_size=squad_size, injured=injured,
                           total_teams=len(table))


# ---------------------------------------------------------------------------
# Routes: squad / player
# ---------------------------------------------------------------------------

@app.route('/squad')
@require_game
def squad():
    gs = get_game_state()
    club = gs.managed_club
    players = Player.query.filter_by(club_id=club.id).all()
    # order by position then ability
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
    return render_template('squad.html', club=club, players=players,
                           lineup_ids=lineup_ids, stats=stats)


@app.route('/player/<int:player_id>')
@require_game
def player_detail(player_id):
    gs = get_game_state()
    player = Player.query.get_or_404(player_id)
    stats = PlayerStat.query.filter_by(
        player_id=player.id, season_id=gs.current_season_id).first()
    value = transfers_mod.get_transfer_value(player)
    return render_template('player.html', player=player, stats=stats,
                           value=value, managed=player.club_id == gs.managed_club_id)


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
    match = season_mod.get_next_match(gs)
    if not match:
        flash('No more matches this season. Process season end.', 'info')
        return redirect(url_for('dashboard'))
    home, away = match.home_club, match.away_club
    home_table = next((s for s in season_mod.get_league_table(
        gs.current_season_id, home.league_id) if s.club_id == home.id), None)
    away_table = next((s for s in season_mod.get_league_table(
        gs.current_season_id, away.league_id) if s.club_id == away.id), None)
    return render_template('match_preview.html', match=match, home=home,
                           away=away, home_table=home_table,
                           away_table=away_table)


@app.route('/match/play/<int:match_id>')
@require_game
def play_match(match_id):
    gs = get_game_state()
    match = Match.query.get_or_404(match_id)
    if match.played:
        return redirect(url_for('match_result', match_id=match_id))

    season = gs.current_season
    league = League.query.get(match.league_id)

    home_score, away_score, events, commentary, stats = engine.simulate_match(
        match.home_club, match.away_club, season, match, gs)

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

    season_mod.update_standings(season, league, match.home_club_id,
                                match.away_club_id, home_score, away_score)
    engine.update_player_stats(events, season.id)

    # Simulate the rest of that match-day across the league
    season_mod.simulate_other_matches(season, league, match.match_date, gs, app)

    # Advance the game date to the match date
    gs.current_date = match.match_date

    # Post-match news
    mc = gs.managed_club
    we_home = match.home_club_id == mc.id
    our_score = home_score if we_home else away_score
    their_score = away_score if we_home else home_score
    opp = match.away_club if we_home else match.home_club
    if our_score > their_score:
        verdict = 'win'
    elif our_score == their_score:
        verdict = 'draw'
    else:
        verdict = 'defeat'
    season_mod.add_news(
        gs,
        f"{mc.short_name} {home_score}-{away_score} {opp.short_name}"
        if we_home else f"{opp.short_name} {home_score}-{away_score} {mc.short_name}",
        f"A {verdict} for {mc.name} against {opp.name}.",
        category='result')

    transfers_mod.ai_transfers(gs, gs.current_date)
    db.session.commit()

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
    league = League.query.get(match.league_id)
    table = season_mod.get_league_table(gs.current_season_id, league.id)
    # other results that day
    others = Match.query.filter_by(
        season_id=gs.current_season_id, league_id=league.id,
        match_date=match.match_date, played=True).all()
    others = [m for m in others if m.id != match.id]
    return render_template('match_result.html', match=match, events=events,
                           table=table, others=others,
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

    return render_template('transfers.html', club=club, results=results,
                           query=query, position=position, max_value=max_value)


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
