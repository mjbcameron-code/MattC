"""
Club history and season awards.

Tracks in-save records: biggest win, highest attendance, transfer records,
all-time goal scorers. Also computes season-end awards for the managed club.
"""
from sqlalchemy import func
from .models import db, Player, PlayerStat, Match, Transfer


def get_season_awards(gs):
    """Season performance awards for the managed club."""
    sid = gs.current_season_id
    mc = gs.managed_club_id

    my_stats = (PlayerStat.query
                .filter_by(season_id=sid, club_id=mc)
                .all())

    rated = [s for s in my_stats if s.appearances >= 5 and s.total_rating > 0]
    pots = (max(rated, key=lambda s: s.total_rating / s.appearances)
            if rated else None)

    top_scorer = (max(my_stats, key=lambda s: s.goals)
                  if my_stats else None)
    if top_scorer and not top_scorer.goals:
        top_scorer = None

    top_assister = (max(my_stats, key=lambda s: s.assists)
                    if my_stats else None)
    if top_assister and not top_assister.assists:
        top_assister = None

    most_apps = (max(my_stats, key=lambda s: s.appearances)
                 if my_stats else None)

    played = Match.query.filter(
        Match.season_id == sid,
        Match.played == True,
        (Match.home_club_id == mc) | (Match.away_club_id == mc)
    ).all()

    best_result = worst_result = None
    bw = bm = 0

    for m in played:
        our = (m.home_score or 0) if m.home_club_id == mc else (m.away_score or 0)
        their = (m.away_score or 0) if m.home_club_id == mc else (m.home_score or 0)
        opp = m.away_club if m.home_club_id == mc else m.home_club
        margin = our - their
        if margin > bw:
            bw = margin
            best_result = {'match': m, 'our': our, 'their': their, 'opp': opp}
        if margin < bm:
            bm = margin
            worst_result = {'match': m, 'our': our, 'their': their, 'opp': opp}

    total_goals = sum(
        (m.home_score or 0) if m.home_club_id == mc else (m.away_score or 0)
        for m in played
    )
    clean_sheets = sum(
        1 for m in played
        if ((m.away_score or 0) if m.home_club_id == mc else (m.home_score or 0)) == 0
    )
    wins = sum(
        1 for m in played
        if (((m.home_score or 0) if m.home_club_id == mc else (m.away_score or 0)) >
            ((m.away_score or 0) if m.home_club_id == mc else (m.home_score or 0)))
    )

    return {
        'pots': pots,
        'top_scorer': top_scorer,
        'top_assister': top_assister,
        'most_apps': most_apps,
        'best_result': best_result,
        'worst_result': worst_result,
        'total_goals': total_goals,
        'clean_sheets': clean_sheets,
        'wins': wins,
        'played_count': len(played),
    }


def get_club_records(gs):
    """All-time records for this save."""
    mc = gs.managed_club_id

    all_played = Match.query.filter(
        Match.played == True,
        (Match.home_club_id == mc) | (Match.away_club_id == mc)
    ).all()

    biggest_win = biggest_loss = highest_att = None
    bw = bl = 0
    best_att = 0

    for m in all_played:
        our = (m.home_score or 0) if m.home_club_id == mc else (m.away_score or 0)
        their = (m.away_score or 0) if m.home_club_id == mc else (m.home_score or 0)
        opp = m.away_club if m.home_club_id == mc else m.home_club
        margin = our - their

        if margin > bw:
            bw = margin
            biggest_win = {'match': m, 'our': our, 'their': their, 'opp': opp}
        if margin < bl:
            bl = margin
            biggest_loss = {'match': m, 'our': our, 'their': their, 'opp': opp}
        if m.attendance and m.attendance > best_att:
            best_att = m.attendance
            highest_att = {'match': m, 'attendance': m.attendance, 'opp': opp}

    record_buy = (Transfer.query
                  .filter_by(to_club_id=mc)
                  .filter(Transfer.fee > 0)
                  .order_by(Transfer.fee.desc()).first())
    record_sale = (Transfer.query
                   .filter_by(from_club_id=mc)
                   .filter(Transfer.fee > 0)
                   .order_by(Transfer.fee.desc()).first())

    scorer_rows = (db.session.query(
        PlayerStat.player_id,
        func.sum(PlayerStat.goals).label('total_goals'),
        func.sum(PlayerStat.appearances).label('total_apps'),
    )
    .filter_by(club_id=mc)
    .group_by(PlayerStat.player_id)
    .order_by(func.sum(PlayerStat.goals).desc())
    .limit(10).all())

    top_scorers_alltime = []
    for row in scorer_rows:
        if row.total_goals and row.total_goals > 0:
            p = Player.query.get(row.player_id)
            if p:
                top_scorers_alltime.append({
                    'player': p,
                    'goals': row.total_goals,
                    'apps': row.total_apps,
                })

    return {
        'biggest_win': biggest_win,
        'biggest_loss': biggest_loss,
        'highest_attendance': highest_att,
        'record_buy': record_buy,
        'record_sale': record_sale,
        'top_scorers_alltime': top_scorers_alltime,
        'matches_played': len(all_played),
    }


def post_season_awards_news(gs):
    """Create news items for the season's standout performers."""
    from .season import add_news

    awards = get_season_awards(gs)

    if awards['pots']:
        s = awards['pots']
        name = s.player.name if s.player else 'Unknown'
        avg = round(s.total_rating / 10.0 / s.appearances, 1)
        pos = s.player.position if s.player else 'player'
        add_news(gs,
                 f"{name} wins Player of the Season",
                 f"{name} has been voted {gs.managed_club.name}'s Player of the Season "
                 f"after an outstanding campaign. The {pos} averaged {avg}/10 across "
                 f"{s.appearances} appearances.", 'general')

    if awards['top_scorer'] and awards['top_scorer'].goals >= 5:
        s = awards['top_scorer']
        name = s.player.name if s.player else 'Unknown'
        add_news(gs,
                 f"{name} finishes as top scorer with {s.goals} goals",
                 f"{name} led {gs.managed_club.name}'s attack this season, "
                 f"finding the net {s.goals} times in {s.appearances} appearances. "
                 f"The goals dried up for nobody.", 'general')

    if awards['best_result']:
        r = awards['best_result']
        add_news(gs,
                 f"Season review: best result was {r['our']}-{r['their']} vs {r['opp'].short_name}",
                 f"{gs.managed_club.name}'s standout result this season was the "
                 f"{r['our']}-{r['their']} victory over {r['opp'].name} in the "
                 f"{r['match'].competition}.", 'general')
