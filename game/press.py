"""
Press & media system.

Pre-match press conference: one journalist question with 3-4 answer choices.
Each answer adjusts squad morale, fan happiness, and board confidence.
Post-match: an auto-generated headline and DoF reaction news item.
"""
import random
from .season import add_news, get_recent_results, get_league_table

# ---------------------------------------------------------------------------
# Question pool
# ---------------------------------------------------------------------------
# Each question has:
#   id, context (list), text, answers (list of dicts with
#   key / label / morale_delta / fan_delta / board_delta / flavour)
# ---------------------------------------------------------------------------

_Q = [

    # ── General ──────────────────────────────────────────────────────────────

    {
        'id': 'expectations',
        'ctx': ['general'],
        'text': "What are your expectations for this match?",
        'answers': [
            {'key': 'bullish',
             'label': "We're going out to win. Three points is the only acceptable outcome.",
             'morale_delta': 3, 'fan_delta': 2, 'board_delta': 1,
             'flavour': "The dressing room is energised by your bold words."},
            {'key': 'measured',
             'label': "We're well prepared and looking forward to the challenge.",
             'morale_delta': 1, 'fan_delta': 0, 'board_delta': 1,
             'flavour': "A professional response. The board are satisfied."},
            {'key': 'cautious',
             'label': "We respect the opposition. It will be a tough ninety minutes.",
             'morale_delta': 0, 'fan_delta': -1, 'board_delta': 0,
             'flavour': "A safe answer — no controversy, no excitement."},
            {'key': 'brash',
             'label': "Frankly, this is a match we should be winning comfortably.",
             'morale_delta': 5, 'fan_delta': 2, 'board_delta': -2,
             'flavour': "The squad are fired up — though the opposition will have seen those quotes too."},
        ],
    },
    {
        'id': 'squad_fitness',
        'ctx': ['general'],
        'text': "How is the squad looking ahead of the weekend?",
        'answers': [
            {'key': 'upbeat',
             'label': "Everyone is fit, motivated, and raring to go.",
             'morale_delta': 3, 'fan_delta': 1, 'board_delta': 0,
             'flavour': "Your upbeat words lift the atmosphere in training."},
            {'key': 'honest',
             'label': "We have a couple of knocks but the squad depth is strong.",
             'morale_delta': 0, 'fan_delta': 0, 'board_delta': 1,
             'flavour': "Measured. Nothing to alarm anyone."},
            {'key': 'secret',
             'label': "You'll have to wait and see the team sheet on matchday.",
             'morale_delta': 0, 'fan_delta': -1, 'board_delta': 0,
             'flavour': "Deliberately vague — the press write it as evasion."},
        ],
    },
    {
        'id': 'opponent_respect',
        'ctx': ['general'],
        'text': "What do you make of your opponents this weekend?",
        'answers': [
            {'key': 'respectful',
             'label': "They're a quality side. This will be a proper test of where we are.",
             'morale_delta': 0, 'fan_delta': 0, 'board_delta': 1,
             'flavour': "A gracious assessment. The press give you a positive write-up."},
            {'key': 'confident',
             'label': "We've done our homework and we believe we match up well.",
             'morale_delta': 2, 'fan_delta': 1, 'board_delta': 0,
             'flavour': "The squad take heart from the analysis."},
            {'key': 'praising',
             'label': "They've been excellent this season — we'll have to be at our very best.",
             'morale_delta': -1, 'fan_delta': -1, 'board_delta': 0,
             'flavour': "Perhaps too generous — some in the dressing room seem deflated."},
            {'key': 'dismissive',
             'label': "Honestly? We're the better team and this match is ours to lose.",
             'morale_delta': 4, 'fan_delta': 3, 'board_delta': -1,
             'flavour': "Bold. The fans love it. The board wince slightly."},
        ],
    },
    {
        'id': 'tactics',
        'ctx': ['general'],
        'text': "Will you be making tactical adjustments for this fixture?",
        'answers': [
            {'key': 'secret',
             'label': "We never discuss tactics before a game — you'll see on the day.",
             'morale_delta': 0, 'fan_delta': 0, 'board_delta': 0,
             'flavour': "Safe and professional. Nothing given away."},
            {'key': 'attacking',
             'label': "We intend to play on the front foot and take the game to them.",
             'morale_delta': 2, 'fan_delta': 2, 'board_delta': 0,
             'flavour': "The attacking intent excites the supporters."},
            {'key': 'defensive',
             'label': "Being organised and hard to beat is the priority.",
             'morale_delta': 0, 'fan_delta': -2, 'board_delta': 1,
             'flavour': "Pragmatic. The board approve; some fans groan."},
        ],
    },
    {
        'id': 'recent_signing',
        'ctx': ['general'],
        'text': "How are you expecting your recent signings to contribute?",
        'answers': [
            {'key': 'excited',
             'label': "They've settled in brilliantly. We expect them to make an immediate impact.",
             'morale_delta': 4, 'fan_delta': 2, 'board_delta': 1,
             'flavour': "The new arrivals feel welcomed and motivated."},
            {'key': 'patient',
             'label': "We'll integrate them carefully — no point rushing anyone.",
             'morale_delta': 1, 'fan_delta': 0, 'board_delta': 1,
             'flavour': "A sensible approach. Nobody is over-hyped."},
            {'key': 'pressure',
             'label': "We've invested in them because we need results. The pressure is there.",
             'morale_delta': -2, 'fan_delta': 0, 'board_delta': 1,
             'flavour': "A direct message. The new arrivals feel the weight of expectation."},
        ],
    },

    # ── Bad form ─────────────────────────────────────────────────────────────

    {
        'id': 'bad_form_why',
        'ctx': ['bad_form'],
        'text': "You've had a difficult run of results. What's going wrong?",
        'answers': [
            {'key': 'defiant',
             'label': "Results haven't gone our way but I believe in this squad completely.",
             'morale_delta': 3, 'fan_delta': 1, 'board_delta': -1,
             'flavour': "The squad appreciate the public backing. The board are less certain."},
            {'key': 'honest',
             'label': "We're not performing to the level we know we can. We have to fix that.",
             'morale_delta': -1, 'fan_delta': 0, 'board_delta': 2,
             'flavour': "A frank admission. The board respect the honesty."},
            {'key': 'excuses',
             'label': "Injuries and fixture congestion have made life very difficult.",
             'morale_delta': 0, 'fan_delta': -2, 'board_delta': -1,
             'flavour': "The press aren't buying it. The board exchange glances."},
            {'key': 'fighting',
             'label': "We're going to turn this around starting this weekend. Mark my words.",
             'morale_delta': 4, 'fan_delta': 2, 'board_delta': 1,
             'flavour': "Fighting talk. The dressing room responds."},
        ],
    },
    {
        'id': 'pressure_question',
        'ctx': ['bad_form'],
        'text': "Is the board still fully behind you despite the recent run?",
        'answers': [
            {'key': 'confident',
             'label': "Absolutely. We have a clear plan and everyone is aligned.",
             'morale_delta': 1, 'fan_delta': 0, 'board_delta': 1,
             'flavour': "Calm and assured. A good answer under pressure."},
            {'key': 'no_comment',
             'label': "I don't concern myself with that. My focus is on the next match.",
             'morale_delta': 0, 'fan_delta': 0, 'board_delta': 0,
             'flavour': "Stoic deflection. No new headlines."},
            {'key': 'dig',
             'label': "Results like ours deserve more patience than some people show.",
             'morale_delta': 2, 'fan_delta': 1, 'board_delta': -3,
             'flavour': "A veiled dig at the board. Risky territory — the headlines write themselves."},
        ],
    },
    {
        'id': 'changes_needed',
        'ctx': ['bad_form'],
        'text': "Are you planning to make changes to the team or approach?",
        'answers': [
            {'key': 'yes_changes',
             'label': "Yes — when results aren't coming, something has to change.",
             'morale_delta': -2, 'fan_delta': 1, 'board_delta': 2,
             'flavour': "Some players are on edge, wondering if they're out. The board are pleased."},
            {'key': 'stick',
             'label': "I believe in the group. We'll stick together and this will turn.",
             'morale_delta': 3, 'fan_delta': 0, 'board_delta': -1,
             'flavour': "Loyalty. The squad appreciate it — the board are watching closely."},
            {'key': 'vague',
             'label': "We're always looking to improve. I'll assess everything after this fixture.",
             'morale_delta': 0, 'fan_delta': 0, 'board_delta': 0,
             'flavour': "Uncommitted. Buys time without saying anything."},
        ],
    },

    # ── Good form ─────────────────────────────────────────────────────────────

    {
        'id': 'good_form_key',
        'ctx': ['good_form'],
        'text': "You're on an impressive run. What's the key to the recent form?",
        'answers': [
            {'key': 'team_effort',
             'label': "It's a collective effort — everyone is pulling in the same direction.",
             'morale_delta': 3, 'fan_delta': 1, 'board_delta': 1,
             'flavour': "The whole squad feel valued. Good spirit all round."},
            {'key': 'system',
             'label': "The system is clicking and the players have fully bought into it.",
             'morale_delta': 1, 'fan_delta': 0, 'board_delta': 2,
             'flavour': "The board are pleased with the organised approach."},
            {'key': 'cautious',
             'label': "We're not getting carried away — there are still many games to go.",
             'morale_delta': 0, 'fan_delta': -1, 'board_delta': 1,
             'flavour': "Feet on the ground. The fans would prefer a bit more swagger."},
            {'key': 'ambitious',
             'label': "We've found our rhythm and we're not planning to stop here.",
             'morale_delta': 4, 'fan_delta': 3, 'board_delta': 1,
             'flavour': "Ambition and belief. The supporters are dreaming."},
        ],
    },

    # ── Cup ───────────────────────────────────────────────────────────────────

    {
        'id': 'cup_ambition',
        'ctx': ['cup'],
        'text': "How seriously are you taking this cup run?",
        'answers': [
            {'key': 'all_in',
             'label': "We want to win every competition we enter. The cup is no exception.",
             'morale_delta': 3, 'fan_delta': 3, 'board_delta': 1,
             'flavour': "Cup fever building. The fans are invested."},
            {'key': 'rotation',
             'label': "We'll use it to give some squad players valuable minutes.",
             'morale_delta': -2, 'fan_delta': -2, 'board_delta': 0,
             'flavour': "The fringe players are pleased; the supporters are not."},
            {'key': 'balanced',
             'label': "We want to progress, but the league has to remain the priority.",
             'morale_delta': 0, 'fan_delta': 0, 'board_delta': 1,
             'flavour': "Balanced and realistic. No controversy created."},
        ],
    },

    # ── European ──────────────────────────────────────────────────────────────

    {
        'id': 'euro_occasion',
        'ctx': ['european'],
        'text': "What does this European fixture mean to the club?",
        'answers': [
            {'key': 'proud',
             'label': "It's a huge occasion. We intend to represent the club with pride.",
             'morale_delta': 4, 'fan_delta': 3, 'board_delta': 1,
             'flavour': "European pride surges through the whole squad."},
            {'key': 'focused',
             'label': "It's another game. We prepare exactly the same way we always do.",
             'morale_delta': 1, 'fan_delta': 0, 'board_delta': 1,
             'flavour': "Professional calm. The squad are cool and ready."},
            {'key': 'ambitious',
             'label': "We're not here just to participate. We believe we can go deep in this.",
             'morale_delta': 5, 'fan_delta': 4, 'board_delta': 0,
             'flavour': "Ambitious words. The supporters are dreaming big."},
        ],
    },

    # ── Title race ────────────────────────────────────────────────────────────

    {
        'id': 'title_challenge',
        'ctx': ['title'],
        'text': "Can you genuinely challenge for the title this season?",
        'answers': [
            {'key': 'deny',
             'label': "Let's not get ahead of ourselves. There are many games to go.",
             'morale_delta': 0, 'fan_delta': -2, 'board_delta': 1,
             'flavour': "Very cautious. The fans are a little frustrated."},
            {'key': 'believe',
             'label': "Why not? We have the quality and we believe in ourselves.",
             'morale_delta': 4, 'fan_delta': 4, 'board_delta': 1,
             'flavour': "Title talk has arrived. The dressing room is buzzing."},
            {'key': 'deflect',
             'label': "Our aim is to improve every week. The table takes care of itself.",
             'morale_delta': 1, 'fan_delta': 0, 'board_delta': 1,
             'flavour': "Safe politics. No new pressure created."},
        ],
    },

    # ── Relegation ────────────────────────────────────────────────────────────

    {
        'id': 'survival',
        'ctx': ['danger'],
        'text': "Are you concerned about the team's league position right now?",
        'answers': [
            {'key': 'fighting',
             'label': "Not concerned — determined. We have the character to get out of this.",
             'morale_delta': 4, 'fan_delta': 2, 'board_delta': 0,
             'flavour': "Fighting words. The dressing room responds."},
            {'key': 'honest',
             'label': "Of course I'm concerned. We're not where we want to be.",
             'morale_delta': -1, 'fan_delta': -1, 'board_delta': 1,
             'flavour': "Honest. At least the board know you understand the gravity."},
            {'key': 'blame',
             'label': "Our performances deserve more than the results suggest.",
             'morale_delta': 1, 'fan_delta': -2, 'board_delta': -2,
             'flavour': "The press are unconvinced. The board look uncomfortable."},
        ],
    },
]

# Build lookup dict
_Q_BY_ID = {q['id']: q for q in _Q}


# ---------------------------------------------------------------------------
# Context selection
# ---------------------------------------------------------------------------

def _get_contexts(game_state, match):
    """Determine which question contexts apply to this match."""
    contexts = ['general']

    # Recent form (last 5 managed-club matches)
    recent = get_recent_results(game_state, 5)
    mc_id = game_state.managed_club_id
    wins = losses = 0
    for m in recent:
        our = m.home_score if m.home_club_id == mc_id else m.away_score
        opp = m.away_score if m.home_club_id == mc_id else m.home_score
        if our is not None and opp is not None:
            if our > opp:   wins += 1
            elif our < opp: losses += 1
    if losses >= 2:  contexts.append('bad_form')
    if wins >= 3:    contexts.append('good_form')

    # League position
    try:
        table = get_league_table(game_state.current_season_id,
                                 game_state.managed_club.league_id)
        pos = next((i + 1 for i, s in enumerate(table)
                    if s.club_id == mc_id), None)
        if pos:
            if pos <= 3:                    contexts.append('title')
            if pos >= len(table) - 4:       contexts.append('danger')
    except Exception:
        pass

    # Competition
    comp = match.competition or ''
    if 'Cup' in comp:                       contexts.append('cup')
    if 'CL' in comp or 'UEFA' in comp:      contexts.append('european')

    return contexts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_pre_match_question(game_state, match):
    """Return a (question_dict, context_list) for the pre-match presser."""
    contexts = _get_contexts(game_state, match)
    # Prefer context-specific questions; fall back to general
    specific = [q for q in _Q if any(c in contexts for c in q['ctx']) and q['ctx'] != ['general']]
    general  = [q for q in _Q if q['ctx'] == ['general']]
    pool = specific if specific else general
    question = random.choice(pool)
    return question, contexts


def get_question_by_id(q_id):
    """Look up a question by its id string (for POST handling)."""
    return _Q_BY_ID.get(q_id)


def apply_pre_match_answer(game_state, question, answer_key):
    """Apply the DoF's answer: morale, fan happiness, board confidence.
    Returns the answer dict on success, None if key not found."""
    from .models import db, Player
    from .commercial import update_fan_happiness

    answer = next((a for a in question['answers'] if a['key'] == answer_key), None)
    if not answer:
        return None

    md = answer['morale_delta']
    if md:
        for p in Player.query.filter_by(club_id=game_state.managed_club_id).all():
            p.morale = max(0, min(100, (p.morale or 70) + md))

    if answer['fan_delta']:
        update_fan_happiness(game_state, event=None, delta=answer['fan_delta'])

    if answer['board_delta']:
        game_state.board_confidence = max(
            0, min(100, (game_state.board_confidence or 50) + answer['board_delta']))

    mc = game_state.managed_club
    add_news(game_state,
             f"Pre-match press conference: {mc.short_name}",
             f'Q: "{question["text"]}"\n\n'
             f'"{answer["label"]}"\n\n'
             f'{answer["flavour"]}',
             'press')
    db.session.commit()
    return answer


# ---------------------------------------------------------------------------
# Post-match headline
# ---------------------------------------------------------------------------

_WIN_BIG   = ["{club} demolish {opp} in stunning {comp} performance",
              "Dominant {club} rout {opp} — a statement result",
              "{opp} no match for a clinical {club} side"]
_WIN_COMF  = ["{club} too strong for {opp} in {comp}",
              "Comfortable {club} victory against {opp}",
              "{club} pick up three points against {opp}"]
_WIN_CLOSE = ["{club} grind out vital win against {opp}",
              "Hard-fought victory keeps {club} on track",
              "Late {club} winner edges {opp} in tense {comp} clash"]
_DRAW      = ["Honours even as {club} and {opp} share the spoils",
              "Competitive stalemate between {club} and {opp}",
              "A point apiece — {club} will feel they deserved more"]
_LOSS_CLOSE= ["{opp} edge out {club} in tight {comp} encounter",
              "Narrow defeat for {club} against {opp}",
              "Fine margins cost {club} against a solid {opp}"]
_LOSS_BIG  = ["{club} suffer heavy defeat — questions to be answered",
              "Miserable afternoon as {opp} run riot against {club}",
              "{club} well beaten — {opp} too strong on the day"]

_WIN_QUOTES  = ["We deserved that. The lads worked hard.",
                "Three points is what matters. Very pleased.",
                "Great result. We'll enjoy this one."]
_DRAW_QUOTES = ["We can do better. A point's a point but we wanted three.",
                "I think we deserved more from that game.",
                "Difficult match — fair result in the end."]
_LOSS_QUOTES = ["Very disappointed. That's not good enough from us.",
                "Hard to take but we stay positive and move on.",
                "A day to forget. We'll address it on Monday."]
_LOSS_BIG_Q  = ["A day to forget. We'll look at this on video and address it.",
                "Not good enough. The players know that.",
                "Difficult to explain a performance like that."]


def generate_post_match_headline(game_state, our_score, their_score, opp, competition):
    """Add a post-match media reaction news item."""
    mc   = game_state.managed_club
    diff = abs(our_score - their_score)
    ctx  = {'club': mc.short_name, 'opp': opp.short_name, 'comp': competition}

    if our_score > their_score:
        pool   = _WIN_BIG if diff >= 3 else (_WIN_COMF if diff >= 2 else _WIN_CLOSE)
        quotes = _WIN_QUOTES
        mood   = ("A magnificent result." if diff >= 3 else
                  "A solid and deserved win." if diff >= 2 else
                  "Delighted to get the points.")
    elif our_score == their_score:
        pool, quotes, mood = _DRAW, _DRAW_QUOTES, "A frustrating night — wanted all three."
    else:
        if diff >= 3:
            pool, quotes, mood = _LOSS_BIG,  _LOSS_BIG_Q, "A very poor afternoon — no excuses."
        else:
            pool, quotes, mood = _LOSS_CLOSE, _LOSS_QUOTES, "Disappointed. We were in the game."

    headline = random.choice(pool).format(**ctx)
    quote    = random.choice(quotes)
    body     = f"{our_score}–{their_score}. {mood}\n\n\"{quote}\""
    add_news(game_state, f"[{competition}] {headline}", body, 'press')
