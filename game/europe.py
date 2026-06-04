"""
European competition — Champions League and UEFA Cup.

Champions League: 16 clubs (top 4 from each of 4 leagues) in 4 groups of 4.
Single-leg group stage over 3 match-days; QF/SF/Final knockouts.

UEFA Cup: 8-team single-elimination bracket (QF → SF → Final).
"""
import random
from .models import db, Match, Club, League, NewsItem

# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

CL_GROUPS = ['CL Group A', 'CL Group B', 'CL Group C', 'CL Group D']

CL_GROUP_DATES = [
    '2001-09-11',
    '2001-09-25',
    '2001-10-16',
]

CL_KNOCKOUT = [
    ('CL QF',    '2002-02-19'),
    ('CL SF',    '2002-04-02'),
    ('CL Final', '2002-05-14'),
]

UEFA_ROUNDS = [
    ('UEFA QF',    '2002-02-26'),
    ('UEFA SF',    '2002-04-10'),
    ('UEFA Final', '2002-05-08'),
]

_CL_KO_NAMES  = [r[0] for r in CL_KNOCKOUT]
_UEFA_NAMES   = [r[0] for r in UEFA_ROUNDS]
_ALL_EURO     = CL_GROUPS + _CL_KO_NAMES + _UEFA_NAMES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_match(season_id, h_id, a_id, date_str, comp):
    db.session.add(Match(
        season_id=season_id, league_id=None,
        home_club_id=h_id, away_club_id=a_id,
        match_date=date_str, competition=comp, played=False))


def _top_clubs(league_name, limit=4):
    lg = League.query.filter_by(name=league_name).first()
    if not lg:
        return []
    return Club.query.filter_by(league_id=lg.id).order_by(
        Club.reputation.desc()).limit(limit).all()


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def generate_champions_league(season, prev_standings=None):
    """Generate CL group stage. prev_standings: dict[league_name → [Club…]]."""
    if Match.query.filter_by(season_id=season.id,
                              competition='CL Group A').count():
        return

    # Collect top-4 from each of the 4 leagues
    qualified = []
    for league_name in ('Premier League', 'La Liga', 'Serie A', 'Bundesliga'):
        if prev_standings and league_name in prev_standings:
            qualified.extend(prev_standings[league_name][:4])
        else:
            qualified.extend(_top_clubs(league_name, 4))

    seen, clubs = set(), []
    for c in qualified:
        if c.id not in seen:
            clubs.append(c)
            seen.add(c.id)
    clubs = clubs[:16]
    if len(clubs) < 8:
        return

    random.shuffle(clubs)
    groups = [clubs[i * 4:(i + 1) * 4] for i in range(4)]

    # Round-robin single-leg per group across 3 match-days
    # MD pairings for 4 teams: (0v1,2v3), (0v2,1v3), (0v3,1v2)
    md_pairings = [[(0, 1), (2, 3)], [(0, 2), (1, 3)], [(0, 3), (1, 2)]]

    for g_idx, group in enumerate(groups):
        comp = CL_GROUPS[g_idx]
        for md_idx, pairs in enumerate(md_pairings):
            date = CL_GROUP_DATES[md_idx]
            for h_i, a_i in pairs:
                _make_match(season.id, group[h_i].id, group[a_i].id, date, comp)

    db.session.commit()


def generate_uefa_cup(season, prev_standings=None):
    """Generate UEFA Cup starting from QF (8 clubs)."""
    if Match.query.filter_by(season_id=season.id,
                              competition='UEFA QF').count():
        return

    clubs = []
    # 5th and 6th from PL
    if prev_standings and 'Premier League' in prev_standings:
        clubs.extend(prev_standings['Premier League'][4:6])
    else:
        clubs.extend(_top_clubs('Premier League', 6)[4:6])

    # Fill from other leagues (5th place each)
    for league_name in ('La Liga', 'Serie A', 'Bundesliga', 'Premier League'):
        if len(clubs) >= 8:
            break
        if prev_standings and league_name in prev_standings:
            extras = prev_standings[league_name]
        else:
            extras = _top_clubs(league_name, 8)
        for c in extras:
            if c.id not in {x.id for x in clubs}:
                clubs.append(c)
                if len(clubs) >= 8:
                    break

    clubs = clubs[:8]
    if len(clubs) < 4:
        return

    random.shuffle(clubs)
    date = UEFA_ROUNDS[0][1]
    for i in range(0, len(clubs), 2):
        _make_match(season.id, clubs[i].id, clubs[i + 1].id, date, 'UEFA QF')

    db.session.commit()


# ---------------------------------------------------------------------------
# Group standings
# ---------------------------------------------------------------------------

def get_group_standings(season_id, group_comp):
    """Return a sorted list of dicts for a CL group."""
    matches = Match.query.filter_by(
        season_id=season_id, competition=group_comp, played=True).all()

    table = {}
    for m in matches:
        for cid, gf, ga in ((m.home_club_id, m.home_score, m.away_score),
                             (m.away_club_id, m.away_score, m.home_score)):
            if cid not in table:
                table[cid] = dict(club=None, P=0, W=0, D=0, L=0,
                                  GF=0, GA=0, Pts=0)
            r = table[cid]
            r['P']  += 1
            r['GF'] += gf
            r['GA'] += ga
            if gf > ga:
                r['W']   += 1; r['Pts'] += 3
            elif gf == ga:
                r['D']   += 1; r['Pts'] += 1
            else:
                r['L'] += 1

    for cid, r in table.items():
        r['club'] = Club.query.get(cid)
        r['GD']   = r['GF'] - r['GA']

    # Include clubs with 0 played (not yet appeared)
    all_group = Match.query.filter_by(
        season_id=season_id, competition=group_comp).all()
    for m in all_group:
        for cid in (m.home_club_id, m.away_club_id):
            if cid not in table:
                table[cid] = dict(club=Club.query.get(cid),
                                  P=0, W=0, D=0, L=0, GF=0, GA=0, GD=0, Pts=0)

    return sorted(table.values(),
                  key=lambda r: (-r['Pts'], -(r['GF'] - r['GA']), -r['GF']))


# ---------------------------------------------------------------------------
# Advancement
# ---------------------------------------------------------------------------

def _winners_of(season_id, comp):
    winners = []
    for m in Match.query.filter_by(season_id=season_id,
                                    competition=comp, played=True).all():
        if m.home_score > m.away_score:
            winners.append(m.home_club)
        elif m.away_score > m.home_score:
            winners.append(m.away_club)
        else:
            winners.append(random.choice([m.home_club, m.away_club]))
    return winners


def _advance_cl_groups(season, game_state=None):
    """If all group matches are complete, generate the QF draw."""
    if Match.query.filter_by(season_id=season.id,
                              competition='CL QF').count():
        return

    qualifiers = []
    for grp in CL_GROUPS:
        total  = Match.query.filter_by(season_id=season.id,
                                        competition=grp).count()
        played = Match.query.filter_by(season_id=season.id,
                                        competition=grp, played=True).count()
        if not total or played < total:
            return
        standings = get_group_standings(season.id, grp)
        qualifiers.extend(r['club'] for r in standings[:2])

    random.shuffle(qualifiers)
    date = CL_KNOCKOUT[0][1]
    for i in range(0, len(qualifiers), 2):
        _make_match(season.id, qualifiers[i].id,
                    qualifiers[i + 1].id, date, 'CL QF')
    db.session.commit()

    if game_state:
        _draw_news(game_state, season, 'CL QF', 'Champions League',
                   'Quarter-Final', date)


def _advance_cl_ko(season, completed, game_state=None):
    total  = Match.query.filter_by(season_id=season.id,
                                    competition=completed).count()
    played = Match.query.filter_by(season_id=season.id,
                                    competition=completed, played=True).count()
    if not total or played < total:
        return

    if completed not in _CL_KO_NAMES:
        return
    idx = _CL_KO_NAMES.index(completed)
    if idx + 1 >= len(CL_KNOCKOUT):
        if game_state:
            _winner_news(season, completed, 'Champions League', game_state)
        return

    next_name, next_date = CL_KNOCKOUT[idx + 1]
    if Match.query.filter_by(season_id=season.id,
                              competition=next_name).count():
        return

    winners = _winners_of(season.id, completed)
    random.shuffle(winners)
    for i in range(0, len(winners), 2):
        _make_match(season.id, winners[i].id, winners[i + 1].id,
                    next_date, next_name)
    db.session.commit()

    if game_state:
        _draw_news(game_state, season, next_name, 'Champions League',
                   next_name.replace('CL ', ''), next_date)


def _advance_uefa(season, completed, game_state=None):
    total  = Match.query.filter_by(season_id=season.id,
                                    competition=completed).count()
    played = Match.query.filter_by(season_id=season.id,
                                    competition=completed, played=True).count()
    if not total or played < total:
        return

    if completed not in _UEFA_NAMES:
        return
    idx = _UEFA_NAMES.index(completed)
    if idx + 1 >= len(UEFA_ROUNDS):
        if game_state:
            _winner_news(season, completed, 'UEFA Cup', game_state)
        return

    next_name, next_date = UEFA_ROUNDS[idx + 1]
    if Match.query.filter_by(season_id=season.id,
                              competition=next_name).count():
        return

    winners = _winners_of(season.id, completed)
    random.shuffle(winners)
    for i in range(0, len(winners), 2):
        _make_match(season.id, winners[i].id, winners[i + 1].id,
                    next_date, next_name)
    db.session.commit()

    if game_state:
        _draw_news(game_state, season, next_name, 'UEFA Cup',
                   next_name.replace('UEFA ', ''), next_date)


def check_and_advance_europe(season, game_state=None):
    """Check and advance all European rounds after each match."""
    _advance_cl_groups(season, game_state)
    for rnd in _CL_KO_NAMES:
        _advance_cl_ko(season, rnd, game_state)
    for rnd in _UEFA_NAMES:
        _advance_uefa(season, rnd, game_state)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def simulate_europe_day(season, match_date, game_state):
    """Simulate all AI European matches on or before match_date."""
    from .engine import simulate_match as _sim, update_player_stats, record_participation
    from .models import MatchEvent

    pending = Match.query.filter_by(
        season_id=season.id, played=False).filter(
        Match.competition.in_(_ALL_EURO),
        Match.match_date <= match_date,
    ).all()

    mid = game_state.managed_club_id
    for m in pending:
        if m.home_club_id == mid or m.away_club_id == mid:
            continue
        hs, as_, events, _, _, participants = _sim(m.home_club, m.away_club, season, m)
        # Knockout rounds need a winner
        if m.competition not in CL_GROUPS and hs == as_:
            if random.random() < 0.5:
                hs += 1
            else:
                as_ += 1
        m.home_score, m.away_score, m.played = hs, as_, True
        for ev in events:
            db.session.add(MatchEvent(
                match_id=m.id, minute=ev['minute'], event_type=ev['type'],
                player_id=ev.get('player_id'),
                assist_player_id=ev.get('assist_player_id'),
                club_id=ev.get('club_id'),
                description=ev.get('description', '')))
        update_player_stats(events, season.id)
        record_participation(participants, season.id, m.id)

    db.session.commit()
    check_and_advance_europe(season, game_state)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def get_euro_matches_for_club(club_id, season_id):
    return Match.query.filter(
        Match.season_id == season_id,
        Match.competition.in_(_ALL_EURO),
        (Match.home_club_id == club_id) | (Match.away_club_id == club_id)
    ).order_by(Match.match_date).all()


def is_in_europe(club_id, season_id):
    return bool(get_euro_matches_for_club(club_id, season_id))


def get_our_cl_group(club_id, season_id):
    """Return the group competition string for the managed club, or None."""
    for grp in CL_GROUPS:
        m = Match.query.filter_by(
            season_id=season_id, competition=grp).filter(
            (Match.home_club_id == club_id) |
            (Match.away_club_id == club_id)).first()
        if m:
            return grp
    return None


# ---------------------------------------------------------------------------
# News helpers
# ---------------------------------------------------------------------------

def _add_news(gs, headline, body):
    if not gs:
        return
    db.session.add(NewsItem(
        game_state_id=gs.id, date=gs.current_date,
        headline=headline, body=body, category='cup'))
    db.session.commit()


def _draw_news(game_state, season, comp, cup_name, round_label, date):
    mc_id = game_state.managed_club_id
    our   = Match.query.filter_by(
        season_id=season.id, competition=comp).filter(
        (Match.home_club_id == mc_id) |
        (Match.away_club_id == mc_id)).first()
    if our:
        opp = our.away_club if our.home_club_id == mc_id else our.home_club
        _add_news(game_state,
                  f'{cup_name} {round_label}: {game_state.managed_club.name} vs {opp.name}',
                  f'The {comp} draw has been made. '
                  f'{game_state.managed_club.name} face {opp.name} on {date}.')
    else:
        _add_news(game_state,
                  f'{game_state.managed_club.name} exit the {cup_name}',
                  f'The club did not progress to the {comp}.')


def _winner_news(season, final_comp, cup_name, game_state):
    m = Match.query.filter_by(season_id=season.id,
                               competition=final_comp, played=True).first()
    if not m:
        return
    winner = m.home_club if (m.home_score or 0) >= (m.away_score or 0) else m.away_club
    venue  = 'Cardiff' if cup_name == 'Champions League' else 'Feyenoord Stadium'
    _add_news(game_state,
              f'{winner.name} win the {cup_name}!',
              f'{winner.name} are crowned {cup_name} winners after a '
              f'memorable final at {venue}!')
