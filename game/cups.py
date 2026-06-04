"""
Cup competition management — FA Cup and League Cup (Worthington Cup).

Matches are stored as regular Match rows with descriptive `competition` strings
(e.g. 'FA Cup R3', 'League Cup QF').  Advancement is triggered automatically
after every managed-club match via check_and_advance_cups().
"""
import random
from .models import db, Match, Club, Season, League, NewsItem

# ---------------------------------------------------------------------------
# Round schedules
# ---------------------------------------------------------------------------

FA_CUP = [
    ('FA Cup R3',    1,  5),
    ('FA Cup R4',    1, 26),
    ('FA Cup R5',    2, 16),
    ('FA Cup QF',    3,  9),
    ('FA Cup SF',    4, 14),
    ('FA Cup Final', 5,  4),
]

LEAGUE_CUP = [
    ('League Cup R2',    9, 18),
    ('League Cup R3',   10, 30),
    ('League Cup R4',   11, 27),
    ('League Cup QF',   12, 18),
    ('League Cup SF',    1, 22),
    ('League Cup Final', 2, 24),
]


def _resolve_date(season, month, day):
    """Resolve a (month, day) within a season to a 'YYYY-MM-DD' string.
    Aug–Dec fall in the season's start year; Jan–Jul in the following year."""
    year = season.year if month >= 7 else season.year + 1
    return f"{year:04d}-{month:02d}-{day:02d}"

LOWER_LEAGUE_NAMES = [
    'Norwich City', 'Preston North End', 'Wolverhampton Wanderers',
    'Cardiff City', 'Burnley', 'Sheffield United',
    'Millwall', 'Rotherham United', 'Bradford City',
    'Crystal Palace', 'Coventry City', 'Nottingham Forest',
]

_FA_ROUNDS  = [r[0] for r in FA_CUP]
_LC_ROUNDS  = [r[0] for r in LEAGUE_CUP]


def _pl_clubs():
    """Return Premier League clubs only (for English cup competitions)."""
    pl = League.query.filter_by(name='Premier League').first()
    if pl:
        return Club.query.filter_by(league_id=pl.id).order_by(
            Club.reputation.desc()).all()
    # fallback
    return Club.query.filter(Club.reputation >= 50).order_by(
        Club.reputation.desc()).all()


def _filler_club(name):
    """Lower-league FA Cup team — stored in a Championship league to avoid
    polluting PL fixture generation or the League Cup draw."""
    c = Club.query.filter_by(name=name).first()
    if c:
        return c
    champ = League.query.filter_by(name='Championship').first()
    if not champ:
        champ = League(name='Championship', country='England', level=2)
        db.session.add(champ)
        db.session.flush()
    c = Club(name=name, short_name=name.split()[0], league_id=champ.id,
             reputation=42, budget=500000, wage_budget=60000,
             primary_color='#777777', secondary_color='#ffffff')
    db.session.add(c)
    db.session.flush()
    return c


def _make_match(season_id, h_id, a_id, date_str, comp):
    db.session.add(Match(season_id=season_id, league_id=None,
                         home_club_id=h_id, away_club_id=a_id,
                         match_date=date_str, competition=comp, played=False))


def generate_fa_cup(season):
    if Match.query.filter_by(season_id=season.id, competition='FA Cup R3').count():
        return
    clubs = list(_pl_clubs())
    for name in LOWER_LEAGUE_NAMES:
        clubs.append(_filler_club(name))
    teams = clubs[:32]
    random.shuffle(teams)
    for i in range(0, 32, 2):
        _make_match(season.id, teams[i].id, teams[i+1].id,
                    _resolve_date(season, FA_CUP[0][1], FA_CUP[0][2]), 'FA Cup R3')
    db.session.commit()


def generate_league_cup(season):
    if Match.query.filter_by(season_id=season.id, competition='League Cup R2').count():
        return
    teams = list(_pl_clubs())
    random.shuffle(teams)
    if len(teams) % 2:
        teams.append(teams[0])
    for i in range(0, len(teams), 2):
        _make_match(season.id, teams[i].id, teams[i+1].id,
                    _resolve_date(season, LEAGUE_CUP[0][1], LEAGUE_CUP[0][2]), 'League Cup R2')
    db.session.commit()


def _winners_of(season_id, round_name):
    winners = []
    for m in Match.query.filter_by(season_id=season_id, competition=round_name,
                                   played=True).all():
        if m.home_score > m.away_score:
            winners.append(m.home_club)
        elif m.away_score > m.home_score:
            winners.append(m.away_club)
        else:
            winners.append(random.choice([m.home_club, m.away_club]))
    return winners


def advance_round(season, completed_round, game_state=None):
    """Generate the next cup round if `completed_round` is fully played."""
    total = Match.query.filter_by(season_id=season.id,
                                  competition=completed_round).count()
    played = Match.query.filter_by(season_id=season.id,
                                   competition=completed_round,
                                   played=True).count()
    if not total or played < total:
        return False

    schedule = FA_CUP if 'FA Cup' in completed_round else LEAGUE_CUP
    rounds   = [r[0] for r in schedule]
    if completed_round not in rounds:
        return False
    idx = rounds.index(completed_round)
    if idx + 1 >= len(schedule):
        # Competition over — post news
        if game_state:
            _news_winner(season, completed_round, game_state)
        return False

    next_name, next_month, next_day = schedule[idx + 1]
    next_date = _resolve_date(season, next_month, next_day)
    if Match.query.filter_by(season_id=season.id, competition=next_name).count():
        return True  # already drawn

    winners = _winners_of(season.id, completed_round)
    random.shuffle(winners)
    for i in range(0, len(winners) - 1, 2):
        _make_match(season.id, winners[i].id, winners[i+1].id, next_date, next_name)
    db.session.commit()

    if game_state:
        cup = 'FA Cup' if 'FA Cup' in next_name else 'League Cup'
        managed_id = game_state.managed_club_id
        our_match = Match.query.filter_by(
            season_id=season.id, competition=next_name).filter(
            (Match.home_club_id == managed_id) | (Match.away_club_id == managed_id)
        ).first()
        if our_match:
            opp = (our_match.away_club if our_match.home_club_id == managed_id
                   else our_match.home_club)
            _add_news(game_state,
                      f"{cup} {next_name.split()[-1]} Draw: vs {opp.name}",
                      f"The {next_name} draw has been made. "
                      f"{game_state.managed_club.name} will face "
                      f"{opp.name} on {next_date}.")
        else:
            _add_news(game_state,
                      f"{game_state.managed_club.name} knocked out of the {cup}",
                      f"Unfortunately {game_state.managed_club.name} did not "
                      f"progress to the {next_name}.")
    return True


def check_and_advance_cups(season, game_state):
    """Advance any cup round whose matches are all complete."""
    for rnd in _FA_ROUNDS + _LC_ROUNDS:
        advance_round(season, rnd, game_state)


def simulate_cup_day(season, match_date, game_state):
    """Simulate all AI cup matches on or before match_date."""
    from .engine import simulate_match as _sim, update_player_stats, record_participation
    from .models import MatchEvent

    pending = Match.query.filter_by(season_id=season.id, played=False).filter(
        Match.competition.like('%Cup%'),
        Match.match_date <= match_date,
    ).all()

    for m in pending:
        mid = game_state.managed_club_id
        if m.home_club_id == mid or m.away_club_id == mid:
            continue
        hs, as_, events, _, _, participants = _sim(m.home_club, m.away_club, season, m)
        # Cups must have a winner — ET goal for draws
        if hs == as_:
            if random.random() < 0.5:
                hs += 1
            else:
                as_ += 1
        m.home_score, m.away_score, m.played = hs, as_, True
        for ev in events:
            db.session.add(MatchEvent(
                match_id=m.id, minute=ev['minute'], event_type=ev['type'],
                player_id=ev.get('player_id'), assist_player_id=ev.get('assist_player_id'),
                club_id=ev.get('club_id'), description=ev.get('description', '')))
        update_player_stats(events, season.id)
        record_participation(participants, season.id, m.id)

    db.session.commit()
    check_and_advance_cups(season, game_state)


def get_cup_matches_for_club(club_id, season_id):
    return Match.query.filter(
        Match.season_id == season_id,
        Match.competition.like('%Cup%'),
        (Match.home_club_id == club_id) | (Match.away_club_id == club_id)
    ).order_by(Match.match_date).all()


def _news_winner(season, final_round, game_state):
    m = Match.query.filter_by(season_id=season.id, competition=final_round,
                               played=True).first()
    if not m:
        return
    winner = m.home_club if m.home_score > m.away_score else m.away_club
    cup = 'FA Cup' if 'FA Cup' in final_round else 'League Cup'
    _add_news(game_state,
              f"{winner.name} win the {cup}!",
              f"{winner.name} are the {cup} winners after the final at "
              f"{'Cardiff' if 'FA Cup' in final_round else 'Millennium Stadium'}!")


def _add_news(gs, headline, body):
    if not gs:
        return
    db.session.add(NewsItem(game_state_id=gs.id, date=gs.current_date,
                            headline=headline, body=body, category='cup'))
    db.session.commit()
