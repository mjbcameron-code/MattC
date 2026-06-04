import random
from datetime import date, timedelta
from .models import db, Match, Standing, Season, Club, League, NewsItem


MATCH_DAYS = [
    # (week, month, day) offsets from season start (Aug 18 2001)
    # 38 match weeks for a 20-team league
]


def generate_fixtures(season, league):
    """Generate a full round-robin fixture list for all clubs in the league."""
    clubs = Club.query.filter_by(league_id=league.id).all()
    if len(clubs) < 2:
        return

    # Clear existing fixtures for this season/league
    Match.query.filter_by(season_id=season.id, league_id=league.id).delete()

    # Round-robin via the circle method
    club_ids = [c.id for c in clubs]
    if len(club_ids) % 2 == 1:
        club_ids.append(None)  # odd count -> one club rests each round
    n = len(club_ids)
    rounds = n - 1
    half = n // 2

    # Start date: first Saturday of August 2001
    start_date = date(2001, 8, 18)

    all_fixtures = []
    arr = club_ids[:]
    for round_num in range(rounds):
        for i in range(half):
            h, a = arr[i], arr[n - 1 - i]
            if h is None or a is None:
                continue  # the rotating bye -> club rests this round
            # Alternate home/away by round so a club isn't always at home
            if round_num % 2 == 0:
                all_fixtures.append((round_num + 1, h, a))
            else:
                all_fixtures.append((round_num + 1, a, h))
        # Rotate all clubs except the first, fixed one
        arr = [arr[0]] + [arr[-1]] + arr[1:-1]

    # Second half of the season = reverse fixtures (home/away swapped)
    second_half = [(r + rounds, a, h) for r, h, a in all_fixtures]
    all_fixtures = all_fixtures + second_half
    random.shuffle(all_fixtures)

    # Assign dates: one match per week roughly, Saturdays
    match_date = start_date
    week_num = 1
    last_week = 0
    for i, (week, h_id, a_id) in enumerate(sorted(all_fixtures, key=lambda x: x[0])):
        if week != last_week:
            if last_week != 0:
                match_date += timedelta(days=7)
            last_week = week
        m = Match(
            season_id=season.id,
            league_id=league.id,
            home_club_id=h_id,
            away_club_id=a_id,
            match_date=match_date.strftime('%Y-%m-%d'),
            match_week=week,
            competition='League',
            played=False,
        )
        db.session.add(m)

    db.session.commit()


def init_standings(season, league):
    """Create Standing rows for all clubs in the league."""
    Standing.query.filter_by(season_id=season.id, league_id=league.id).delete()
    clubs = Club.query.filter_by(league_id=league.id).all()
    for club in clubs:
        s = Standing(season_id=season.id, league_id=league.id, club_id=club.id)
        db.session.add(s)
    db.session.commit()


def update_standings(season, league, home_club_id, away_club_id, home_score, away_score):
    """Update the league table after a match result."""
    h_standing = Standing.query.filter_by(
        season_id=season.id, league_id=league.id, club_id=home_club_id).first()
    a_standing = Standing.query.filter_by(
        season_id=season.id, league_id=league.id, club_id=away_club_id).first()

    if not h_standing:
        h_standing = Standing(season_id=season.id, league_id=league.id, club_id=home_club_id)
        db.session.add(h_standing)
    if not a_standing:
        a_standing = Standing(season_id=season.id, league_id=league.id, club_id=away_club_id)
        db.session.add(a_standing)

    h_standing.played += 1
    a_standing.played += 1
    h_standing.goals_for += home_score
    h_standing.goals_against += away_score
    a_standing.goals_for += away_score
    a_standing.goals_against += home_score

    if home_score > away_score:
        h_standing.won += 1
        h_standing.points += 3
        a_standing.lost += 1
    elif home_score == away_score:
        h_standing.drawn += 1
        h_standing.points += 1
        a_standing.drawn += 1
        a_standing.points += 1
    else:
        a_standing.won += 1
        a_standing.points += 3
        h_standing.lost += 1

    db.session.commit()


def simulate_other_matches(season, league, match_date, game_state, app):
    """Simulate all other matches on the same match day (not the managed club's match)."""
    from .engine import simulate_match as eng_sim, update_player_stats, record_participation
    from .models import MatchEvent

    other_matches = Match.query.filter_by(
        season_id=season.id,
        league_id=league.id,
        match_date=match_date,
        played=False,
    ).all()

    results = []
    for m in other_matches:
        if (m.home_club_id == game_state.managed_club_id or
                m.away_club_id == game_state.managed_club_id):
            continue
        h_score, a_score, events, _, _, participants = eng_sim(m.home_club, m.away_club, season, m)
        m.home_score = h_score
        m.away_score = a_score
        m.played = True
        for ev in events:
            me = MatchEvent(
                match_id=m.id,
                minute=ev['minute'],
                event_type=ev['type'],
                player_id=ev.get('player_id'),
                assist_player_id=ev.get('assist_player_id'),
                club_id=ev.get('club_id'),
                description=ev.get('description', ''),
            )
            db.session.add(me)
        update_standings(season, league, m.home_club_id, m.away_club_id, h_score, a_score)
        update_player_stats(events, season.id)
        record_participation(participants, season.id, m.id)
        results.append((m, h_score, a_score))

    db.session.commit()
    return results


def get_next_match(game_state):
    """Get the next unplayed match for the managed club."""
    from .models import Match
    return Match.query.filter(
        Match.season_id == game_state.current_season_id,
        Match.played == False,
        (Match.home_club_id == game_state.managed_club_id) |
        (Match.away_club_id == game_state.managed_club_id)
    ).order_by(Match.match_date).first()


def get_league_table(season_id, league_id):
    """Return sorted league standings."""
    standings = Standing.query.filter_by(
        season_id=season_id, league_id=league_id).all()
    return sorted(standings, key=lambda s: (
        -s.points, -(s.goals_for - s.goals_against), -s.goals_for))


def get_club_form(club_id, season_id, limit=5):
    """Last N results for any club across all competitions."""
    return Match.query.filter(
        Match.season_id == season_id,
        Match.played == True,
        (Match.home_club_id == club_id) | (Match.away_club_id == club_id)
    ).order_by(Match.match_date.desc()).limit(limit).all()


def get_recent_results(game_state, limit=5):
    """Get recent results for managed club."""
    return Match.query.filter(
        Match.season_id == game_state.current_season_id,
        Match.played == True,
        (Match.home_club_id == game_state.managed_club_id) |
        (Match.away_club_id == game_state.managed_club_id)
    ).order_by(Match.match_date.desc()).limit(limit).all()


def add_news(game_state, headline, body, category='general'):
    news = NewsItem(
        game_state_id=game_state.id,
        date=game_state.current_date,
        headline=headline,
        body=body,
        category=category,
    )
    db.session.add(news)
    db.session.commit()


# ---------------------------------------------------------------------------
# Season lifecycle
# ---------------------------------------------------------------------------

def is_league_season_over(game_state):
    """True once every league match in the *managed club's league* is played."""
    league_id = game_state.managed_club.league_id
    total = Match.query.filter_by(season_id=game_state.current_season_id,
                                  competition='League', league_id=league_id).count()
    played = Match.query.filter_by(season_id=game_state.current_season_id,
                                   competition='League', league_id=league_id,
                                   played=True).count()
    return total > 0 and total == played


def process_new_season(game_state):
    """Age players, handle contracts, generate a fresh season with cups."""
    import random as _rnd
    from .models import Player, Suspension

    season = game_state.current_season
    league = game_state.managed_club.league
    table = get_league_table(season.id, league.id)
    mc = game_state.managed_club
    position = next((i + 1 for i, s in enumerate(table)
                     if s.club_id == mc.id), len(table))
    relegated = [s.club_id for s in table[-3:]] if len(table) >= 20 else []

    # Return any loan players before resetting the squad
    from game.transfers import return_loans
    return_loans(game_state)

    # Capture league tables for European qualification before overwriting
    from .models import League as LeagueModel
    prev_standings = {}
    for lg in LeagueModel.query.filter(
            LeagueModel.name.in_(['Premier League', 'La Liga',
                                  'Serie A', 'Bundesliga'])).all():
        t = get_league_table(season.id, lg.id)
        prev_standings[lg.name] = [s.club for s in t]

    # ---- Age and develop players ----
    from game.transfers import get_transfer_value
    for p in Player.query.all():
        if p.is_youth:
            continue  # youth players are aged separately in age_youth_players()
        p.age += 1
        # Training quality multiplier: level 1=0.6x ... level 5=1.4x
        tl = getattr(p.club, 'training_level', 3) if p.club else 3
        tl_factor = 0.6 + (tl - 1) * 0.2
        if p.age <= 28 and p.current_ability < p.potential_ability:
            gap = p.potential_ability - p.current_ability
            if p.age <= 24:
                raw = _rnd.randint(0, min(10, gap))
            else:  # 25-28: slower growth
                raw = _rnd.randint(0, min(2, gap))
            p.current_ability += int(raw * tl_factor)
        elif p.age >= 33:
            p.current_ability = max(1, p.current_ability - _rnd.randint(0, 5))
        p.value = get_transfer_value(p)

    # ---- Contract expiry ----
    new_year = season.year + 1
    for p in Player.query.filter(Player.contract_end <= new_year).all():
        if _rnd.random() < 0.35:
            p.club_id = None           # leaves on free
            p.contract_end = new_year + _rnd.randint(2, 4)
        else:
            p.contract_end = new_year + _rnd.randint(2, 4)  # auto-renewed

    # ---- Manager aging and contract management ----
    from .models import Manager
    for mgr in Manager.query.all():
        mgr.age += 1

    club_mgr = game_state.managed_club.head_coach
    if club_mgr:
        if club_mgr.contract_end <= new_year:
            if random.random() < 0.4:
                add_news(game_state, f"{club_mgr.name} leaves on contract expiry",
                         f"{club_mgr.name}'s contract has expired and he has elected "
                         f"not to renew. The club must find a new head coach.", 'staff')
                from game.staff import _release_manager
                _release_manager(club_mgr)
                club_mgr = None
            else:
                club_mgr.contract_end = new_year + 2
                club_mgr.wage = int(club_mgr.wage * 1.05)

        if club_mgr:
            current_conf = game_state.board_confidence or 50
            if current_conf < 30:
                club_mgr.satisfaction = max(0, (club_mgr.satisfaction or 70) - 8)
            drift = 65 - (club_mgr.satisfaction or 70)
            club_mgr.satisfaction = max(0, min(100, (club_mgr.satisfaction or 70) + drift // 4))

    # ---- Clear old suspensions ----
    Suspension.query.delete()

    # ---- New season ----
    short = str(new_year + 1)[-2:]
    new_season = Season(year=new_year, name=f"{new_year}/{short}")
    db.session.add(new_season)
    db.session.flush()

    generate_fixtures(new_season, league)
    init_standings(new_season, league)

    # For other leagues too
    for lg in League.query.filter(League.id != league.id).all():
        generate_fixtures(new_season, lg)
        init_standings(new_season, lg)

    from game.cups import generate_fa_cup, generate_league_cup
    generate_fa_cup(new_season)
    generate_league_cup(new_season)

    from game.europe import generate_champions_league, generate_uefa_cup
    generate_champions_league(new_season, prev_standings)
    generate_uefa_cup(new_season, prev_standings)

    # ---- Club reputation progression ----
    for lg in League.query.all():
        lg_table = get_league_table(season.id, lg.id)
        total = len(lg_table)
        for i, s in enumerate(lg_table):
            pos = i + 1
            if pos == 1:
                delta = 4
            elif pos <= 4:
                delta = 2
            elif pos <= total // 2:
                delta = 1
            elif pos >= total - 2:
                delta = -5
            else:
                delta = -1
            s.club.reputation = max(1, min(100, s.club.reputation + delta))

    # Slight budget boost (summer window)
    for club in Club.query.all():
        club.budget = int(club.budget * 1.08)

    game_state.current_season_id = new_season.id
    game_state.current_date = f"{new_year}-08-18"

    # ---- Youth academy ----
    from game.academy import age_youth_players, generate_intake
    age_youth_players(game_state)
    generate_intake(game_state)

    # ---- Update wage cap for new season ----
    from game import commercial as _comm
    proj_rev = _comm.get_summary(game_state).get('proj_season_revenue', 0)
    game_state.wage_cap_weekly = max(
        game_state.wage_cap_weekly or 0,
        int(proj_rev * 0.6 / 52),
    )

    db.session.commit()

    # ---- News ----
    if mc.id in relegated:
        add_news(game_state, f"{mc.name} RELEGATED",
                 f"A disastrous season ends in relegation from the Premier League. "
                 f"The club finished {position}th. The board are furious.", 'general')
    elif position == 1:
        add_news(game_state, f"CHAMPIONS! {mc.name} win the Premier League!",
                 f"What a season! {mc.name} are Premier League champions. "
                 f"The fans are celebrating in the streets.", 'general')
    elif position <= 4:
        add_news(game_state, f"{mc.name} qualify for Europe",
                 f"A top-four finish means European football next season. "
                 f"The board are delighted with a {position}th-place finish.", 'general')

    add_news(game_state, f"Season {new_season.name} begins — welcome back",
             f"The new {new_season.name} season is underway. "
             f"Fixtures have been generated and the transfer window is open. "
             f"Budget: £{mc.budget:,}. Good luck!", 'general')

    # European qualification news
    if position <= 4:
        add_news(game_state, f'{mc.name} qualify for the Champions League!',
                 f'A {position}{"st" if position==1 else "nd" if position==2 else "rd" if position==3 else "th"}-place '
                 f'finish earns Champions League football next season. '
                 f'The group stage draw awaits!', 'general')
    elif position <= 7:
        add_news(game_state, f'{mc.name} qualify for the UEFA Cup!',
                 f'A {position}th-place finish secures UEFA Cup football '
                 f'next season. A reward for a solid campaign.', 'general')

    # Youth intake
    from game.youth import generate_youth_intake
    generate_youth_intake(game_state)

    # Reset board confidence for new season
    from game.board import set_board_target
    set_board_target(game_state)

    from game.setup import auto_pick_lineup
    auto_pick_lineup(game_state)

    from game.staff import check_manager_status, generate_manager_request
    check_manager_status(game_state)
    generate_manager_request(game_state)

    return position, relegated
