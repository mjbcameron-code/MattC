"""Youth academy intake — generates young prospects each new season."""
import random
from .models import db, Player
from data.player_factory import build_player

_NAMES = {
    'English': (
        ['Jack', 'James', 'Harry', 'Liam', 'Oliver', 'George', 'Charlie',
         'Thomas', 'Kieran', 'Ryan', 'Aaron', 'Luke', 'Danny', 'Leon'],
        ['Smith', 'Jones', 'Taylor', 'Brown', 'Davies', 'Wilson', 'Evans',
         'Walker', 'Hughes', 'Roberts', 'Green', 'Clarke', 'Hall', 'Wood'],
    ),
    'Spanish': (
        ['Carlos', 'Miguel', 'Diego', 'Alejandro', 'Pablo', 'Sergio',
         'Javier', 'Adrián', 'Iván', 'Raúl', 'Marcos', 'David'],
        ['García', 'López', 'Martínez', 'González', 'Rodríguez', 'Hernández',
         'Sánchez', 'Pérez', 'Fernández', 'Ruiz', 'Torres', 'Díaz'],
    ),
    'Italian': (
        ['Marco', 'Luca', 'Matteo', 'Lorenzo', 'Giovanni', 'Francesco',
         'Alberto', 'Davide', 'Simone', 'Andrea', 'Paolo', 'Stefano'],
        ['Rossi', 'Ferrari', 'Russo', 'Bianchi', 'Romano', 'Colombo',
         'Conti', 'Esposito', 'Ricci', 'Marino', 'Greco', 'Bruno'],
    ),
    'German': (
        ['Thomas', 'Michael', 'Stefan', 'Andreas', 'Klaus', 'Markus',
         'Jan', 'Lukas', 'Felix', 'Tobias', 'Florian', 'Kevin'],
        ['Müller', 'Schmidt', 'Schneider', 'Fischer', 'Weber', 'Meyer',
         'Hoffmann', 'Wagner', 'Koch', 'Bauer', 'Richter', 'Wolf'],
    ),
    'French': (
        ['Nicolas', 'Thomas', 'Antoine', 'Julien', 'Pierre', 'Romain',
         'Maxime', 'Alexandre', 'Clément', 'Hugo', 'Théo', 'Lucas'],
        ['Martin', 'Bernard', 'Dubois', 'Thomas', 'Robert', 'Petit',
         'Durand', 'Leroy', 'Moreau', 'Simon', 'Laurent', 'Michel'],
    ),
}
_DEFAULT_NAMES = (
    ['Alex', 'Chris', 'Jordan', 'Liam', 'Daniel', 'Ryan', 'Nathan'],
    ['Anderson', 'Johnson', 'Lee', 'Williams', 'Taylor', 'Clark', 'Lewis'],
)

LEAGUE_NATIONALITY = {
    'Premier League': 'English',
    'La Liga':        'Spanish',
    'Serie A':        'Italian',
    'Bundesliga':     'German',
    'Ligue 1':        'French',
}

POSITIONS = ['GK', 'CB', 'RB', 'LB', 'CM', 'RM', 'LM', 'AM', 'ST']


def _pick_name(nationality):
    firsts, lasts = _NAMES.get(nationality, _DEFAULT_NAMES)
    return f"{random.choice(firsts)} {random.choice(lasts)}"


def _next_squad_number(club_id):
    last = (Player.query.filter_by(club_id=club_id)
            .order_by(Player.squad_number.desc()).first())
    return (last.squad_number + 1) if (last and last.squad_number) else 40


def generate_youth_intake(game_state):
    """Add 4–5 youth players (ages 16–18) to the managed club."""
    club    = game_state.managed_club
    lg_name = club.league.name if club.league else 'Premier League'
    nat     = LEAGUE_NATIONALITY.get(lg_name, 'English')
    count   = random.randint(4, 5)

    names = []
    for _ in range(count):
        age       = random.randint(16, 18)
        quality   = random.randint(6, 10)
        potential = random.randint(max(quality, 12), 18)
        position  = random.choice(POSITIONS)
        name      = _pick_name(nat)

        built = build_player(name, nat, age, position, quality, potential)
        attrs = built['attrs']
        p = Player(
            name=built['name'],
            nationality=nat,
            age=age,
            position=built['position'],
            positions=built['positions'],
            club_id=club.id,
            wage=built['wage'],
            value=built['value'],
            contract_end=2006,
            squad_number=_next_squad_number(club.id),
            current_ability=built['current_ability'],
            potential_ability=built['potential_ability'],
            morale=75,
            condition=100,
            is_youth=True,
            **attrs,
        )
        db.session.add(p)
        names.append(name)

    db.session.commit()

    from .season import add_news
    add_news(game_state,
             f'Youth intake: {count} new prospects sign for {club.name}',
             f'The youth academy has produced a new batch of talent. '
             f'Welcome to: {", ".join(names)}. These youngsters have been '
             f'added to your squad and have the potential to develop into '
             f'first-team regulars in time.',
             'general')
    return names
