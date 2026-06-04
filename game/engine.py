import random
from .models import Player, Club, PlayerStat, MatchEvent, db

COMMENTARY = {
    'kick_off': [
        "The referee blows his whistle and we're underway!",
        "And we're off! The match is underway.",
    ],
    'shot_saved': [
        "{shooter} gets a shot away but {gk} makes a solid save.",
        "{gk} is well positioned and palms away {shooter}'s effort.",
        "Good technique from {shooter} but {gk} is equal to it.",
        "{shooter} fires in a low drive, {gk} gets down well to save.",
        "Superb stop from {gk} to deny {shooter}!",
    ],
    'shot_wide': [
        "{shooter}'s shot drifts wide of the post.",
        "{shooter} tries his luck from range but it's off target.",
        "What a chance for {shooter}! But the effort goes just wide.",
        "{shooter} cuts inside and shoots, but it curls just past the post.",
        "{shooter} gets a clear sight of goal but drags the shot wide.",
    ],
    'shot_over': [
        "{shooter} lashes it over the bar.",
        "{shooter} gets too much height on that effort.",
        "A wild shot from {shooter}, sailing high and wide.",
    ],
    'goal': [
        "GOAL! {scorer} fires home to give {team} the lead! {score}",
        "GOAL! {scorer} makes no mistake! {team} are in front! {score}",
        "GOAL! What a finish from {scorer}! The score is now {score}",
        "GOAL! {scorer} slots it coolly past the keeper! {score}",
        "GOAL! {scorer} is clinical! {team} celebrate! {score}",
        "GOAL! {team} score through {scorer}! Brilliant! {score}",
        "GOAL! {scorer} puts {team} ahead! The home crowd goes wild! {score}",
    ],
    'goal_header': [
        "GOAL! {scorer} meets the cross and powers a header home! {score}",
        "GOAL! {scorer} rises highest and nods it in! {team} lead! {score}",
        "GOAL! A powerful header from {scorer}! {score}",
    ],
    'goal_long': [
        "GOAL! {scorer} tries his luck from thirty yards and it flies in! {score}",
        "GOAL! What a strike from {scorer}! From distance and into the net! {score}",
    ],
    'yellow_card': [
        "{player} is booked for a cynical foul.",
        "The referee produces the yellow card for {player}.",
        "{player} goes into the book for persistent fouling.",
        "A reckless challenge from {player} earns a booking.",
    ],
    'red_card': [
        "{player} is sent off! {team} are down to ten men!",
        "Straight red for {player}! The referee had no choice.",
        "{player} sees red! A shocking challenge that deserved to be punished.",
    ],
    'chance': [
        "{team} work a good opening but can't get a shot away.",
        "{player} is played in on goal but the angle is too tight.",
        "A dangerous move from {team} but the final ball lets them down.",
        "{player} gets in behind the defence but fires straight at the keeper.",
        "Close! {player} almost gets on the end of that cross.",
    ],
    'possession': [
        "{team} are enjoying a spell of possession.",
        "{player} keeps the ball well under pressure in midfield.",
        "{team} are passing it around confidently at the back.",
        "Good build-up play from {team} but they can't find the breakthrough.",
    ],
    'corner': [
        "{team} win a corner. {player} steps up to deliver it.",
        "Another corner for {team}. {player} swings it in.",
    ],
    'free_kick': [
        "{team} have a free-kick in a dangerous position. {player} lines it up.",
        "{player} steps up to take the free-kick for {team}.",
    ],
    'half_time': [
        "Half-time! {score} at the break.",
        "The referee blows for half-time. {score}",
        "That's the half-time whistle! {score}",
    ],
    'full_time': [
        "Full-time! The final score is {score}",
        "And that's it! The referee blows for full-time. {score}",
        "The final whistle sounds! {score}",
    ],
    'substitution': [
        "{out} is replaced by {in_player} for {team}.",
        "{team} make a change: {in_player} comes on for {out}.",
    ],
}


def pick(key, **kwargs):
    template = random.choice(COMMENTARY[key])
    return template.format(**kwargs)


def get_squad_for_match(club, game_state=None):
    """Return (starters, subs) for a club, respecting injuries and suspensions."""
    from .models import Lineup
    from .injuries import is_suspended

    def available(p):
        return not p.is_injured and not is_suspended(p.id)

    if game_state and club.id == game_state.managed_club_id:
        lineups = Lineup.query.filter_by(game_state_id=game_state.id).order_by(Lineup.slot).all()
        if lineups:
            starters = [l.player for l in lineups if l.slot <= 11 and available(l.player)]
            subs = [l.player for l in lineups if l.slot > 11 and available(l.player)]
            if len(starters) >= 7:
                return starters, subs
    players = [p for p in Player.query.filter_by(club_id=club.id).order_by(
        Player.current_ability.desc()).all() if available(p)]
    return players[:11], players[11:16]


def team_attack_rating(players):
    """Weighted attack strength based on squad."""
    if not players:
        return 50
    total = 0
    for p in players:
        if p.position == 'GK':
            continue
        if p.position in ('CB', 'RB', 'LB'):
            score = (p.finishing * 0.5 + p.pace * 0.5 + p.heading * 0.5 +
                     p.long_shots * 0.5 + p.decisions * 0.3) / 5
        elif p.position in ('CM', 'RM', 'LM'):
            score = (p.passing * 1.5 + p.creativity * 1.5 + p.finishing * 0.8 +
                     p.long_shots * 0.8 + p.crossing * 0.8 + p.technique * 0.8) / 7.2
        elif p.position in ('AM',):
            score = (p.passing * 1.2 + p.creativity * 1.5 + p.finishing * 1.2 +
                     p.dribbling * 1.0 + p.technique * 1.0) / 5.9
        else:  # ST
            score = (p.finishing * 2.0 + p.off_the_ball * 1.5 + p.pace * 1.0 +
                     p.acceleration * 1.0 + p.composure * 1.2 + p.first_touch * 0.8) / 7.5
        total += score
    return min(100, max(1, total / max(1, len([p for p in players if p.position != 'GK'])) * 5))


def team_defense_rating(players):
    """Weighted defense strength based on squad."""
    if not players:
        return 50
    gk_score = 0
    def_score = 0
    for p in players:
        if p.position == 'GK':
            gk_score = (p.handling * 2.0 + p.reflexes * 2.0 + p.one_on_ones * 1.5 +
                        p.aerial * 1.0 + p.composure * 1.0 + p.concentration * 1.0) / 8.5
        elif p.position in ('CB', 'RB', 'LB'):
            def_score += (p.tackling * 1.5 + p.marking * 1.5 + p.heading * 1.0 +
                          p.concentration * 1.0 + p.composure * 0.8 + p.positioning * 1.2 +
                          p.pace * 0.5) / 7.5
        elif p.position in ('CM', 'RM', 'LM'):
            def_score += (p.tackling * 0.8 + p.marking * 0.5 + p.positioning * 0.8 +
                          p.work_rate * 0.5) / 2.6
    defenders = [p for p in players if p.position in ('CB', 'RB', 'LB')]
    mids = [p for p in players if p.position in ('CM', 'RM', 'LM', 'AM')]
    base = 0
    if defenders:
        base += def_score / len(defenders + mids) if (defenders + mids) else def_score
    if gk_score:
        base = base * 0.6 + gk_score * 0.4
    return min(100, max(1, base * 5))


def pick_scorer(players, exclude_gk=True):
    """Randomly pick a goal scorer weighted by finishing."""
    candidates = [p for p in players if (not exclude_gk or p.position != 'GK')]
    if not candidates:
        return random.choice(players)
    weights = []
    for p in candidates:
        if p.position in ('ST', 'AM'):
            w = p.finishing * 3 + p.off_the_ball * 2
        elif p.position in ('RM', 'LM', 'CM'):
            w = p.finishing * 1.5 + p.long_shots * 1.5
        else:
            w = p.finishing * 0.5 + p.heading * 1
        weights.append(max(1, w))
    return random.choices(candidates, weights=weights, k=1)[0]


def pick_assister(players, scorer, exclude_gk=True):
    """Pick an assister weighted by passing/creativity."""
    candidates = [p for p in players if p.id != scorer.id and
                  (not exclude_gk or p.position != 'GK')]
    if not candidates:
        return None
    weights = [max(1, p.passing * 2 + p.creativity * 2 + p.crossing) for p in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


def pick_yellow(players):
    """Pick a player to receive a yellow card weighted by aggression."""
    outfield = [p for p in players if p.position != 'GK']
    if not outfield:
        return random.choice(players)
    weights = [max(1, p.aggression * 2 + (20 - p.composure)) for p in outfield]
    return random.choices(outfield, weights=weights, k=1)[0]


def simulate_match(home_club, away_club, season, match_obj, game_state=None):
    """
    Simulate a full match. Returns (home_score, away_score, events_list, stats_dict).
    Events list: dicts with minute, type, description, club_id, player_id, etc.
    """
    home_starters, home_subs = get_squad_for_match(home_club, game_state)
    away_starters, away_subs = get_squad_for_match(away_club, game_state)

    if len(home_starters) < 7:
        home_starters = Player.query.filter_by(club_id=home_club.id).limit(11).all()
    if len(away_starters) < 7:
        away_starters = Player.query.filter_by(club_id=away_club.id).limit(11).all()

    h_att = team_attack_rating(home_starters)
    h_def = team_defense_rating(home_starters)
    a_att = team_attack_rating(away_starters)
    a_def = team_defense_rating(away_starters)

    # Morale modifier for managed club only (AI teams default to neutral morale)
    if game_state:
        from .morale import get_morale_multiplier
        mc_id = game_state.managed_club_id
        if home_club.id == mc_id:
            mult = get_morale_multiplier([p.id for p in home_starters])
            h_att *= mult
            h_def *= mult
        elif away_club.id == mc_id:
            mult = get_morale_multiplier([p.id for p in away_starters])
            a_att *= mult
            a_def *= mult

        # Manager tactical ability modifier (or penalty when no manager)
        mgr = getattr(game_state.managed_club, 'head_coach', None)
        if mgr:
            ta = mgr.tactical_ability
            # Fixed ordering (ta>=18 was unreachable in old code); narrower range so
            # even a great manager gives only a 7% boost rather than 15%
            ta_mult = 0.92 if ta <= 6 else (1.07 if ta >= 18 else (1.04 if ta >= 14 else 1.00))
            style = mgr.preferred_style or 'balanced'
        else:
            ta_mult = 0.88  # no manager — modest leaderless penalty
            style = 'balanced'

        if home_club.id == mc_id:
            h_att *= ta_mult
            h_def *= ta_mult
            if style == 'attacking':
                h_att *= 1.06; h_def *= 0.96
            elif style == 'defensive':
                h_att *= 0.96; h_def *= 1.06
        elif away_club.id == mc_id:
            a_att *= ta_mult
            a_def *= ta_mult
            if style == 'attacking':
                a_att *= 1.06; a_def *= 0.96
            elif style == 'defensive':
                a_att *= 0.96; a_def *= 1.06

    HOME_ADVANTAGE = 4  # real PL home advantage is modest (~55% pts at home)

    h_att_eff = h_att + HOME_ADVANTAGE
    a_att_eff = a_att

    events = []
    commentary_log = []
    home_score = 0
    away_score = 0
    home_shots = 0
    away_shots = 0
    home_shots_on = 0
    away_shots_on = 0
    home_possession = 0

    yellow_counts = {p.id: 0 for p in home_starters + away_starters}
    sent_off = set()

    current_home = list(home_starters)
    current_away = list(away_starters)
    home_subs_used = 0
    away_subs_used = 0
    home_sub_pool = list(home_subs)
    away_sub_pool = list(away_subs)

    def score_str():
        return f"{home_club.short_name or home_club.name} {home_score}-{away_score} {away_club.short_name or away_club.name}"

    # Calibrated for ~2.7 goals/game (PL 2024/25 average was 2.71)
    # /320 sensitivity keeps strong vs weak differentials realistic without blowouts
    base_h_chance = 0.175 + (h_att_eff - a_def) / 320
    base_a_chance = 0.148 + (a_att_eff - h_def) / 320
    base_h_chance = max(0.07, min(0.28, base_h_chance))
    base_a_chance = max(0.06, min(0.25, base_a_chance))
    shot_chance = 0.36  # share of possession events that become shots

    commentary_log.append({'minute': 1, 'text': pick('kick_off'), 'type': 'event'})

    for minute in range(1, 91):
        poss = random.random() < (h_att_eff / (h_att_eff + a_att_eff))
        if poss:
            home_possession += 1

        # Home attack
        if random.random() < base_h_chance:
            active_home = [p for p in current_home if p.id not in sent_off]
            active_away = [p for p in current_away if p.id not in sent_off]
            if not active_home or not active_away:
                continue
            r = random.random()
            if r < shot_chance:
                home_shots += 1
                scorer_cand = pick_scorer(active_home)
                gk_cand = next((p for p in active_away if p.position == 'GK'), None)
                gk_name = gk_cand.name.split()[-1] if gk_cand else 'keeper'
                goal_prob = 0.32 + (scorer_cand.finishing - 10) / 60
                goal_prob -= (gk_cand.reflexes - 10) / 80 if gk_cand else 0
                goal_prob = max(0.06, min(0.56, goal_prob))
                if random.random() < goal_prob:
                    home_shots_on += 1
                    home_score += 1
                    assister = pick_assister(active_home, scorer_cand)
                    is_header = random.random() < 0.2
                    is_long = random.random() < 0.08
                    if is_header:
                        text = pick('goal_header', scorer=scorer_cand.name.split()[-1],
                                    team=home_club.short_name or home_club.name, score=score_str())
                    elif is_long:
                        text = pick('goal_long', scorer=scorer_cand.name.split()[-1],
                                    team=home_club.short_name or home_club.name, score=score_str())
                    else:
                        text = pick('goal', scorer=scorer_cand.name.split()[-1],
                                    team=home_club.short_name or home_club.name, score=score_str())
                    events.append({'minute': minute, 'type': 'goal', 'club_id': home_club.id,
                                   'player_id': scorer_cand.id,
                                   'assist_player_id': assister.id if assister else None,
                                   'description': text})
                    commentary_log.append({'minute': minute, 'text': text, 'type': 'goal'})
                else:
                    home_shots_on += random.random() < 0.45
                    if random.random() < 0.5:
                        text = pick('shot_saved', shooter=scorer_cand.name.split()[-1], gk=gk_name)
                    else:
                        text = pick('shot_wide', shooter=scorer_cand.name.split()[-1])
                    commentary_log.append({'minute': minute, 'text': text, 'type': 'shot'})
            elif r < shot_chance + 0.3:
                active_player = random.choice(active_home)
                text = pick('chance', team=home_club.short_name or home_club.name,
                            player=active_player.name.split()[-1])
                commentary_log.append({'minute': minute, 'text': text, 'type': 'chance'})
            else:
                active_player = random.choice(active_home)
                if random.random() < 0.15:
                    text = pick('possession', team=home_club.short_name or home_club.name,
                                player=active_player.name.split()[-1])
                    commentary_log.append({'minute': minute, 'text': text, 'type': 'possession'})

        # Away attack
        if random.random() < base_a_chance:
            active_home = [p for p in current_home if p.id not in sent_off]
            active_away = [p for p in current_away if p.id not in sent_off]
            if not active_home or not active_away:
                continue
            r = random.random()
            if r < shot_chance:
                away_shots += 1
                scorer_cand = pick_scorer(active_away)
                gk_cand = next((p for p in active_home if p.position == 'GK'), None)
                gk_name = gk_cand.name.split()[-1] if gk_cand else 'keeper'
                goal_prob = 0.30 + (scorer_cand.finishing - 10) / 60
                goal_prob -= (gk_cand.reflexes - 10) / 80 if gk_cand else 0
                goal_prob = max(0.05, min(0.52, goal_prob))
                if random.random() < goal_prob:
                    away_shots_on += 1
                    away_score += 1
                    assister = pick_assister(active_away, scorer_cand)
                    is_header = random.random() < 0.2
                    is_long = random.random() < 0.08
                    if is_header:
                        text = pick('goal_header', scorer=scorer_cand.name.split()[-1],
                                    team=away_club.short_name or away_club.name, score=score_str())
                    elif is_long:
                        text = pick('goal_long', scorer=scorer_cand.name.split()[-1],
                                    team=away_club.short_name or away_club.name, score=score_str())
                    else:
                        text = pick('goal', scorer=scorer_cand.name.split()[-1],
                                    team=away_club.short_name or away_club.name, score=score_str())
                    events.append({'minute': minute, 'type': 'goal', 'club_id': away_club.id,
                                   'player_id': scorer_cand.id,
                                   'assist_player_id': assister.id if assister else None,
                                   'description': text})
                    commentary_log.append({'minute': minute, 'text': text, 'type': 'goal'})
                else:
                    away_shots_on += random.random() < 0.45
                    if random.random() < 0.5:
                        text = pick('shot_saved', shooter=scorer_cand.name.split()[-1], gk=gk_name)
                    else:
                        text = pick('shot_wide', shooter=scorer_cand.name.split()[-1])
                    commentary_log.append({'minute': minute, 'text': text, 'type': 'shot'})

        # Yellow cards (random, ~3 per game total)
        if random.random() < 0.022:
            side = random.choice(['home', 'away'])
            pool = [p for p in (current_home if side == 'home' else current_away)
                    if p.id not in sent_off]
            if pool:
                victim = pick_yellow(pool)
                yellow_counts[victim.id] = yellow_counts.get(victim.id, 0) + 1
                team_name = (home_club if side == 'home' else away_club).short_name
                if yellow_counts[victim.id] >= 2:
                    text = pick('red_card', player=victim.name.split()[-1], team=team_name)
                    sent_off.add(victim.id)
                    events.append({'minute': minute, 'type': 'red_card',
                                   'club_id': (home_club if side == 'home' else away_club).id,
                                   'player_id': victim.id, 'description': text})
                    commentary_log.append({'minute': minute, 'text': text, 'type': 'red_card'})
                else:
                    text = pick('yellow_card', player=victim.name.split()[-1])
                    events.append({'minute': minute, 'type': 'yellow_card',
                                   'club_id': (home_club if side == 'home' else away_club).id,
                                   'player_id': victim.id, 'description': text})
                    commentary_log.append({'minute': minute, 'text': text, 'type': 'yellow_card'})

        # Substitutions (70th-85th minute, max 3 per side)
        if 70 <= minute <= 85:
            if home_subs_used < 3 and home_sub_pool and random.random() < 0.04:
                out_player = random.choice([p for p in current_home if p.position != 'GK'
                                            and p.id not in sent_off])
                in_player = home_sub_pool.pop(0)
                text = pick('substitution', out=out_player.name.split()[-1],
                            in_player=in_player.name.split()[-1],
                            team=home_club.short_name or home_club.name)
                commentary_log.append({'minute': minute, 'text': text, 'type': 'substitution'})
                current_home.remove(out_player)
                current_home.append(in_player)
                home_subs_used += 1
            if away_subs_used < 3 and away_sub_pool and random.random() < 0.04:
                out_player = random.choice([p for p in current_away if p.position != 'GK'
                                            and p.id not in sent_off])
                in_player = away_sub_pool.pop(0)
                text = pick('substitution', out=out_player.name.split()[-1],
                            in_player=in_player.name.split()[-1],
                            team=away_club.short_name or away_club.name)
                commentary_log.append({'minute': minute, 'text': text, 'type': 'substitution'})
                current_away.remove(out_player)
                current_away.append(in_player)
                away_subs_used += 1

        # Half-time
        if minute == 45:
            text = pick('half_time', score=score_str())
            commentary_log.append({'minute': 45, 'text': text, 'type': 'half_time'})

    # Full-time
    text = pick('full_time', score=score_str())
    commentary_log.append({'minute': 90, 'text': text, 'type': 'full_time'})

    possession_pct = round(home_possession / 90 * 100)

    stats = {
        'home_shots': home_shots,
        'away_shots': away_shots,
        'home_shots_on': int(home_shots_on),
        'away_shots_on': int(away_shots_on),
        'home_possession': possession_pct,
        'away_possession': 100 - possession_pct,
    }

    return home_score, away_score, events, commentary_log, stats


def _get_or_create_stat(player_id, season_id, club_id):
    """Fetch a PlayerStat, creating one with explicit zero counters if missing.

    SQLAlchemy column defaults are only applied at INSERT time, so a freshly
    constructed row has `None` counters in memory; we initialise them here so
    `+= 1` is always safe before the first commit.
    """
    ps = PlayerStat.query.filter_by(
        player_id=player_id, season_id=season_id, club_id=club_id).first()
    if not ps:
        ps = PlayerStat(player_id=player_id, season_id=season_id, club_id=club_id,
                        appearances=0, goals=0, assists=0,
                        yellow_cards=0, red_cards=0)
        db.session.add(ps)
    return ps


def update_player_stats(events, season_id):
    """Update PlayerStat rows based on match events."""
    for ev in events:
        if not ev.get('player_id') or not ev.get('club_id'):
            continue
        ps = _get_or_create_stat(ev['player_id'], season_id, ev['club_id'])
        if ev['type'] == 'goal':
            ps.goals += 1
            ps.appearances += 1
            if ev.get('assist_player_id'):
                asp = _get_or_create_stat(ev['assist_player_id'], season_id,
                                          ev['club_id'])
                asp.assists += 1
        elif ev['type'] == 'yellow_card':
            ps.yellow_cards += 1
        elif ev['type'] == 'red_card':
            ps.red_cards += 1
    db.session.commit()
