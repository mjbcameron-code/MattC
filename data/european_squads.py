"""Real 2001/02 European squad data for a Championship Manager 01/02 clone.

Leagues covered: La Liga (Spain), Serie A (Italy), Bundesliga (Germany).
Each club is a dict with metadata and a list of players.
Player tuples: (name, nationality, age, position, quality, potential)
Positions: GK, RB, CB, LB, RM, CM, LM, AM, ST
Quality / potential: integers 1-20 approximating real 2001/02 ability.
"""

CLUBS = [
    # -------------------------------------------------------------------------
    # LA LIGA
    # -------------------------------------------------------------------------
    {
        'name': 'Real Madrid',
        'short_name': 'Real Madrid',
        'league': 'La Liga',
        'reputation': 94,
        'budget': 70000000,
        'wage_budget': 2500000,
        'primary_color': '#FFFFFF',
        'secondary_color': '#FEBE10',
        'players': [
            # Goalkeepers
            ('Iker Casillas',       'Spain',     20, 'GK', 16, 20),
            ('Cesar Sanchez',       'Spain',     29, 'GK', 14, 14),
            ('Santiago Canizares',  'Spain',     31, 'GK', 16, 16),  # on loan to Valencia
            # Defenders
            ('Roberto Carlos',      'Brazil',    28, 'LB', 18, 18),
            ('Michel Salgado',      'Spain',     26, 'RB', 16, 16),
            ('Fernando Hierro',     'Spain',     33, 'CB', 16, 16),
            ('Ivan Helguera',       'Spain',     27, 'CB', 15, 15),
            ('Raul Bravo',          'Spain',     21, 'CB', 12, 15),
            ('Carlos Secretario',   'Portugal',  31, 'RB', 12, 12),
            # Midfielders
            ('Claude Makelele',     'France',    28, 'CM', 17, 17),
            ('Zinedine Zidane',     'France',    29, 'CM', 20, 20),
            ('Luis Figo',           'Portugal',  29, 'RM', 19, 19),
            ('Steve McManaman',     'England',   29, 'CM', 14, 14),
            ('Flavio Conceicao',    'Brazil',    28, 'CM', 14, 14),
            ('Ivan Campo',          'Spain',     27, 'CM', 13, 13),
            ('Guti',                'Spain',     24, 'AM', 15, 16),
            # Forwards
            ('Raul',                'Spain',     24, 'ST', 18, 18),
            ('Ronaldo',             'Brazil',    25, 'ST', 17, 20),  # injury comeback
            ('Fernando Morientes',  'Spain',     25, 'ST', 17, 17),
            ('Savio',               'Brazil',    26, 'RM', 13, 13),
            ('Pedro Munitis',       'Spain',     27, 'RM', 13, 13),
        ],
    },
    {
        'name': 'Barcelona',
        'short_name': 'Barcelona',
        'league': 'La Liga',
        'reputation': 90,
        'budget': 55000000,
        'wage_budget': 2000000,
        'primary_color': '#A50044',
        'secondary_color': '#004D98',
        'players': [
            # Goalkeepers
            ('Roberto Bonano',      'Argentina', 32, 'GK', 13, 13),
            ('Victor Valdes',       'Spain',     19, 'GK', 12, 17),
            ('Richard Dutruel',     'France',    30, 'GK', 13, 13),
            # Defenders
            ('Carles Puyol',        'Spain',     23, 'CB', 16, 19),
            ('Frank de Boer',       'Netherlands',31,'CB', 15, 15),
            ('Philippe Christanval','France',    22, 'CB', 13, 16),
            ('Abelardo',            'Spain',     32, 'CB', 14, 14),
            ('Sergi Barjuan',       'Spain',     31, 'LB', 13, 13),
            ('Geovanni',            'Brazil',    23, 'RM', 13, 15),
            ('Michael Reiziger',    'Netherlands',28,'RB', 15, 15),
            # Midfielders
            ('Xavi',                'Spain',     21, 'CM', 15, 19),
            ('Phillip Cocu',        'Netherlands',30,'CM', 15, 15),
            ('Luis Enrique',        'Spain',     31, 'CM', 14, 14),
            ('Marc Overmars',       'Netherlands',28,'LM', 16, 16),
            ('Gaizka Mendieta',     'Spain',     29, 'CM', 15, 15),
            ('Gerard',              'Spain',     26, 'CM', 13, 13),
            ('Andersson',           'Sweden',    27, 'AM', 12, 12),
            # Forwards
            ('Rivaldo',             'Brazil',    29, 'AM', 19, 19),
            ('Patrick Kluivert',    'Netherlands',25,'ST', 17, 17),
            ('Javier Saviola',      'Argentina', 19, 'ST', 15, 19),
            ('Alfonso',             'Spain',     29, 'ST', 13, 13),
            ('Simao',               'Portugal',  22, 'LM', 14, 17),
        ],
    },
    {
        'name': 'Valencia',
        'short_name': 'Valencia',
        'league': 'La Liga',
        'reputation': 84,
        'budget': 28000000,
        'wage_budget': 1100000,
        'primary_color': '#FFFFFF',
        'secondary_color': '#EF7B00',
        'players': [
            # Goalkeepers
            ('Santiago Canizares',  'Spain',     31, 'GK', 16, 16),
            ('Andres Palop',        'Spain',     28, 'GK', 13, 14),
            # Defenders
            ('Roberto Ayala',       'Argentina', 29, 'CB', 17, 17),
            ('Mauricio Pellegrino', 'Argentina', 27, 'CB', 15, 15),
            ('Curro Torres',        'Spain',     25, 'RB', 14, 15),
            ('Amedeo Carboni',      'Italy',     37, 'LB', 13, 13),
            ('Jocelyn Angloma',     'France',    34, 'RB', 13, 13),
            ('Carlos Marchena',     'Spain',     22, 'CB', 13, 16),
            # Midfielders
            ('David Albelda',       'Spain',     24, 'CM', 14, 16),
            ('Gaizka Mendieta',     'Spain',     29, 'CM', 15, 15),
            ('Pablo Aimar',         'Argentina', 22, 'AM', 15, 18),
            ('Vicente Rodriguez',   'Spain',     20, 'LM', 14, 18),
            ('Ruben Baraja',        'Spain',     25, 'CM', 14, 16),
            ('Gerard Lopez',        'Spain',     20, 'CM', 13, 16),
            ('Miguel',              'Portugal',  22, 'RM', 13, 16),
            # Forwards
            ('John Carew',          'Norway',    22, 'ST', 13, 16),
            ('Claudio Lopez',       'Argentina', 28, 'ST', 15, 15),
            ('Mista',               'Spain',     23, 'ST', 14, 16),
            ('Adrian Ilie',         'Romania',   27, 'ST', 13, 13),
            ('Salva Ballesta',      'Spain',     26, 'ST', 14, 14),
        ],
    },
    {
        'name': 'Deportivo de La Coruna',
        'short_name': 'Deportivo',
        'league': 'La Liga',
        'reputation': 80,
        'budget': 22000000,
        'wage_budget': 900000,
        'primary_color': '#6CB4E4',
        'secondary_color': '#FFFFFF',
        'players': [
            # Goalkeepers
            ('Jose Francisco Molina','Spain',    32, 'GK', 15, 15),
            ('Pablo Cavallero',     'Argentina', 28, 'GK', 13, 14),
            # Defenders
            ('Noureddine Naybet',   'Morocco',   32, 'CB', 14, 14),
            ('Donato',              'Brazil',    37, 'CB', 13, 13),
            ('Jorge Andrade',       'Portugal',  23, 'CB', 14, 17),
            ('Manuel Pablo',        'Spain',     25, 'RB', 14, 15),
            ('Enrique Romero',      'Spain',     27, 'LB', 13, 13),
            ('Juan Valeron',        'Spain',     25, 'AM', 16, 17),
            # Midfielders
            ('Fran',                'Spain',     30, 'CM', 14, 14),
            ('Victor Sanchez',      'Spain',     24, 'CM', 13, 15),
            ('Mauro Silva',         'Brazil',    33, 'CM', 14, 14),
            ('Emerson',             'Brazil',    25, 'CM', 15, 16),
            ('Aldo Duscher',        'Argentina', 24, 'CM', 13, 15),
            ('Sergio',              'Spain',     26, 'LM', 13, 13),
            ('Cesar Martin',        'Spain',     28, 'RM', 12, 12),
            # Forwards
            ('Roy Makaay',          'Netherlands',27,'ST', 17, 17),
            ('Diego Tristan',       'Spain',     26, 'ST', 16, 16),
            ('Walter Pandiani',     'Uruguay',   26, 'ST', 14, 14),
            ('Victor',              'Spain',     25, 'ST', 12, 13),
        ],
    },
    {
        'name': 'Celta Vigo',
        'short_name': 'Celta Vigo',
        'league': 'La Liga',
        'reputation': 72,
        'budget': 14000000,
        'wage_budget': 700000,
        'primary_color': '#6DC8E8',
        'secondary_color': '#FFFFFF',
        'players': [
            # Goalkeepers
            ('Richard Dutruel',     'France',    30, 'GK', 13, 13),
            ('Pinto',               'Spain',     29, 'GK', 12, 13),
            # Defenders
            ('Jorge Lopez',         'Spain',     29, 'CB', 13, 13),
            ('Velasco',             'Spain',     27, 'CB', 12, 13),
            ('Juan Caceres',        'Paraguay',  23, 'CB', 13, 15),
            ('Juanfran',            'Spain',     26, 'RB', 13, 14),
            ('Edu Dorcasberro',     'Spain',     25, 'LB', 12, 13),
            # Midfielders
            ('Alexander Mostovoi', 'Russia',    33, 'AM', 15, 15),
            ('Valeri Karpin',       'Russia',    31, 'CM', 14, 14),
            ('Edu',                 'Brazil',    22, 'CM', 13, 16),
            ('Gustavo Lopez',       'Argentina', 29, 'CM', 14, 14),
            ('Sandro',              'Spain',     24, 'LM', 12, 14),
            ('Sergio Fernandez',    'Spain',     23, 'RM', 12, 13),
            ('Michel Salgado',      'Spain',     25, 'RB', 13, 14),
            # Forwards
            ('Benni McCarthy',      'South Africa',24,'ST',14, 15),
            ('Edu Coudet',          'Argentina', 27, 'ST', 13, 13),
            ('Revivo',              'Israel',    28, 'AM', 13, 13),
            ('Alfonso Perez',       'Spain',     28, 'ST', 13, 13),
            ('Fernandez',           'Spain',     24, 'ST', 12, 13),
        ],
    },
    {
        'name': 'Villarreal',
        'short_name': 'Villarreal',
        'league': 'La Liga',
        'reputation': 65,
        'budget': 10000000,
        'wage_budget': 550000,
        'primary_color': '#FFD700',
        'secondary_color': '#005F9E',
        'players': [
            # Goalkeepers
            ('Jose Manuel Reina',   'Spain',     19, 'GK', 13, 18),
            ('Marcelino Fernandez', 'Spain',     31, 'GK', 12, 12),
            # Defenders
            ('Victor Espana',       'Spain',     27, 'CB', 13, 13),
            ('Quique Alvarez',      'Spain',     30, 'CB', 12, 12),
            ('Gonzalo Rodriguez',   'Argentina', 22, 'CB', 12, 15),
            ('Armando',             'Spain',     26, 'RB', 12, 13),
            ('Cesar Arzo',          'Spain',     23, 'LB', 12, 14),
            # Midfielders
            ('Juan Roman Riquelme', 'Argentina', 23, 'AM', 17, 18),
            ('Robert Pires',        'France',    27, 'LM', 15, 16),  # not Villarreal – using Marcos Senna
            ('Marcos Senna',        'Brazil',    25, 'CM', 13, 16),
            ('Victor',              'Spain',     24, 'CM', 13, 14),
            ('Josico',              'Spain',     24, 'CM', 12, 14),
            ('Sonny Anderson',      'Brazil',    29, 'ST', 14, 14),
            ('Javi Calleja',        'Spain',     28, 'RM', 12, 12),
            # Forwards
            ('Alessio Tacchinardi', 'Italy',     27, 'CM', 13, 13),
            ('Guayre',              'Spain',     26, 'ST', 12, 13),
            ('Angel',               'Spain',     22, 'ST', 13, 15),
            ('Marino',              'Spain',     25, 'ST', 12, 12),
            ('Sebastian Fernandez', 'Uruguay',   22, 'RM', 12, 14),
        ],
    },
    {
        'name': 'Sevilla',
        'short_name': 'Sevilla',
        'league': 'La Liga',
        'reputation': 67,
        'budget': 11000000,
        'wage_budget': 600000,
        'primary_color': '#D71920',
        'secondary_color': '#FFFFFF',
        'players': [
            # Goalkeepers
            ('Andres Palop',        'Spain',     28, 'GK', 13, 14),
            ('Juanmi',              'Spain',     25, 'GK', 11, 12),
            # Defenders
            ('Pablo Alfaro',        'Spain',     32, 'CB', 13, 13),
            ('Aitor Karanka',       'Spain',     28, 'CB', 13, 13),
            ('Francisco Gallardo',  'Spain',     26, 'RB', 12, 13),
            ('Javi Navarro',        'Spain',     30, 'CB', 13, 13),
            ('David Castedo',       'Spain',     24, 'LB', 12, 13),
            ('Daniel Alves',        'Brazil',    18, 'RB', 12, 18),
            # Midfielders
            ('Jose Mari',           'Spain',     24, 'AM', 13, 15),
            ('Juan Rodriguez',      'Spain',     24, 'CM', 13, 14),
            ('Jordi Lopez',         'Spain',     26, 'CM', 12, 12),
            ('Renato',              'Brazil',    26, 'RM', 13, 14),
            ('Antonio Puerta',      'Spain',     17, 'LM', 10, 16),
            # Forwards
            ('Darko Kovacevic',     'Yugoslavia',28,'ST', 14, 14),
            ('Jose Antonio Reyes',  'Spain',     18, 'AM', 13, 18),
            ('Fredi Kanoute',       'France',    23, 'ST', 14, 15),
            ('Javi Moreno',         'Spain',     26, 'ST', 13, 14),
            ('Federico Lussenhoff', 'Argentina', 24, 'LM', 11, 13),
        ],
    },
    {
        'name': 'Athletic Club',
        'short_name': 'Athletic Club',
        'league': 'La Liga',
        'reputation': 68,
        'budget': 12000000,
        'wage_budget': 600000,
        'primary_color': '#EE2523',
        'secondary_color': '#FFFFFF',
        'players': [
            # Goalkeepers
            ('Inaki Lafuente',      'Spain',     30, 'GK', 13, 13),
            ('Daniel Aranzubia',    'Spain',     21, 'GK', 12, 15),
            # Defenders
            ('Julen Guerrero',      'Spain',     28, 'AM', 14, 14),
            ('Aitor Larrazabal',    'Spain',     29, 'CB', 12, 12),
            ('Cesar del Amo',       'Spain',     24, 'CB', 12, 14),
            ('Carlos Gurpegui',     'Spain',     21, 'CM', 12, 15),
            ('Inigo Velez',         'Spain',     27, 'CB', 12, 12),
            ('Agustin Garitano',    'Spain',     30, 'LB', 11, 11),
            ('Asier del Horno',     'Spain',     20, 'LB', 12, 16),
            # Midfielders
            ('Joseba Etxeberria',   'Spain',     25, 'RM', 14, 14),
            ('Bingen Zubiaurre',    'Spain',     29, 'CM', 12, 12),
            ('Josu Urkiaga',        'Spain',     26, 'CM', 12, 13),
            ('David Alkorta',       'Spain',     33, 'CB', 12, 12),
            ('Yeste',               'Spain',     22, 'LM', 13, 15),
            ('Jose Angel Iribar',   'Spain',     23, 'CM', 11, 13),
            # Forwards
            ('Ismael Urzaiz',       'Spain',     29, 'ST', 14, 14),
            ('Javier Llorente',     'Spain',     26, 'ST', 13, 13),
            ('Tiko',                'Spain',     24, 'ST', 12, 13),
            ('Ziganda',             'Spain',     32, 'ST', 12, 12),
            ('Boli Bolingoli',      'Belgium',   18, 'LM', 10, 14),
        ],
    },

    # -------------------------------------------------------------------------
    # SERIE A
    # -------------------------------------------------------------------------
    {
        'name': 'Juventus',
        'short_name': 'Juventus',
        'league': 'Serie A',
        'reputation': 92,
        'budget': 60000000,
        'wage_budget': 2200000,
        'primary_color': '#000000',
        'secondary_color': '#FFFFFF',
        'players': [
            # Goalkeepers
            ('Gianluigi Buffon',    'Italy',     23, 'GK', 18, 20),
            ('Edwin van der Sar',   'Netherlands',31,'GK', 16, 16),
            ('Fabian Carini',       'Uruguay',   22, 'GK', 11, 14),
            # Defenders
            ('Lilian Thuram',       'France',    29, 'RB', 18, 18),
            ('Ciro Ferrara',        'Italy',     36, 'CB', 14, 14),
            ('Paolo Montero',       'Uruguay',   31, 'CB', 15, 15),
            ('Mark Iuliano',        'Italy',     29, 'CB', 14, 14),
            ('Gianluca Zambrotta',  'Italy',     24, 'RB', 15, 17),
            ('Igor Tudor',          'Croatia',   24, 'CB', 14, 15),
            ('Nicola Legrottaglie', 'Italy',     24, 'CB', 13, 16),
            # Midfielders
            ('Pavel Nedved',        'Czech Republic',29,'LM',18,18),
            ('Edgar Davids',        'Netherlands',28,'CM', 17, 17),
            ('Antonio Conte',       'Italy',     32, 'CM', 14, 14),
            ('Zinedine Zidane',     'France',    29, 'CM', 20, 20),  # left for Real Madrid summer 2001
            ('Alessio Tacchinardi', 'Italy',     27, 'CM', 13, 13),
            ('Mauro Camoranesi',    'Argentina', 24, 'RM', 14, 16),
            # Forwards
            ('Alessandro Del Piero','Italy',     27, 'ST', 18, 18),
            ('David Trezeguet',     'France',    24, 'ST', 18, 18),
            ('Marcelo Zalayeta',    'Uruguay',   23, 'ST', 12, 14),
            ('Nicola Amoruso',      'Italy',     27, 'ST', 13, 13),
            ('Filippo Inzaghi',     'Italy',     28, 'ST', 16, 16),
        ],
    },
    {
        'name': 'AC Milan',
        'short_name': 'AC Milan',
        'league': 'Serie A',
        'reputation': 91,
        'budget': 58000000,
        'wage_budget': 2100000,
        'primary_color': '#FB090B',
        'secondary_color': '#000000',
        'players': [
            # Goalkeepers
            ('Dida',                'Brazil',    28, 'GK', 17, 17),
            ('Sebastiano Rossi',    'Italy',     37, 'GK', 13, 13),
            ('Christian Abbiati',   'Italy',     24, 'GK', 13, 16),
            # Defenders
            ('Paolo Maldini',       'Italy',     33, 'LB', 18, 18),
            ('Alessandro Costacurta','Italy',    36, 'CB', 15, 15),
            ('Alessandro Nesta',    'Italy',     25, 'CB', 19, 19),
            ('Kaladze',             'Georgia',   23, 'CB', 14, 16),
            ('Serginho',            'Brazil',    31, 'LB', 15, 15),
            ('Dario Simic',         'Croatia',   26, 'RB', 14, 15),
            ('Cosmin Contra',       'Romania',   26, 'RB', 13, 14),
            # Midfielders
            ('Clarence Seedorf',    'Netherlands',25,'CM', 16, 16),
            ('Gennaro Gattuso',     'Italy',     23, 'CM', 16, 18),
            ('Andrea Pirlo',        'Italy',     22, 'CM', 16, 19),
            ('Manuel Rui Costa',    'Portugal',  29, 'AM', 17, 17),
            ('Massimo Ambrosini',   'Italy',     24, 'CM', 14, 16),
            ('Zvonimir Boban',      'Croatia',   32, 'CM', 14, 14),
            # Forwards
            ('Andriy Shevchenko',   'Ukraine',   25, 'ST', 19, 19),
            ('Filippo Inzaghi',     'Italy',     28, 'ST', 18, 18),
            ('Rivaldo',             'Brazil',    29, 'AM', 18, 18),  # arrived summer 2002
            ('Jose Mari',           'Spain',     24, 'ST', 12, 13),
            ('Jon Dahl Tomasson',   'Denmark',   25, 'ST', 14, 15),
        ],
    },
    {
        'name': 'AS Roma',
        'short_name': 'AS Roma',
        'league': 'Serie A',
        'reputation': 88,
        'budget': 40000000,
        'wage_budget': 1600000,
        'primary_color': '#8B1A1A',
        'secondary_color': '#F5C518',
        'players': [
            # Goalkeepers
            ('Francesco Antonioli', 'Italy',     33, 'GK', 14, 14),
            ('Ivan Pelizzoli',      'Italy',     21, 'GK', 12, 15),
            # Defenders
            ('Cafu',                'Brazil',    31, 'RB', 18, 18),
            ('Walter Samuel',       'Argentina', 24, 'CB', 16, 18),
            ('Antonio Carlos',      'Brazil',    27, 'CB', 14, 14),
            ('Aldair',              'Brazil',    35, 'CB', 14, 14),
            ('Jonathan Zebina',     'France',    23, 'RB', 13, 15),
            ('Olivier Dacourt',     'France',    27, 'CM', 15, 15),
            ('Max Tonetto',         'Italy',     27, 'LB', 13, 14),
            # Midfielders
            ('Emerson',             'Brazil',    25, 'CM', 16, 16),
            ('Damiano Tommasi',     'Italy',     27, 'CM', 14, 14),
            ('Hidetoshi Nakata',    'Japan',     25, 'AM', 15, 15),
            ('Cristiano Zanetti',   'Italy',     27, 'CM', 13, 13),
            ('Amedeo Mangone',      'Italy',     23, 'CM', 11, 13),
            # Forwards
            ('Francesco Totti',     'Italy',     25, 'AM', 19, 19),
            ('Gabriel Batistuta',   'Argentina', 32, 'ST', 18, 18),
            ('Vincenzo Montella',   'Italy',     27, 'ST', 17, 17),
            ('Marco Delvecchio',    'Italy',     28, 'ST', 14, 14),
            ('Antonio Cassano',     'Italy',     19, 'ST', 13, 18),
        ],
    },
    {
        'name': 'Inter Milan',
        'short_name': 'Inter',
        'league': 'Serie A',
        'reputation': 89,
        'budget': 50000000,
        'wage_budget': 1900000,
        'primary_color': '#0066B2',
        'secondary_color': '#000000',
        'players': [
            # Goalkeepers
            ('Francesco Toldo',     'Italy',     30, 'GK', 16, 16),
            ('Sebastiano Peruzzi',  'Italy',     31, 'GK', 13, 13),
            ('Gianluca Pagliuca',   'Italy',     36, 'GK', 12, 12),
            # Defenders
            ('Javier Zanetti',      'Argentina', 28, 'RB', 17, 17),
            ('Fabio Cannavaro',     'Italy',     28, 'CB', 17, 17),
            ('Marco Materazzi',     'Italy',     28, 'CB', 13, 15),
            ('Cyril Domoraud',      'Ivory Coast',29,'CB', 13, 13),
            ('Vratislav Gresko',    'Slovakia',  26, 'LB', 13, 14),
            ('Michele Serena',      'Italy',     30, 'LB', 12, 12),
            # Midfielders
            ('Alvaro Recoba',       'Uruguay',   25, 'AM', 17, 17),
            ('Cesar',               'Brazil',    27, 'CM', 14, 15),
            ('Mohamed Kallon',      'Sierra Leone',22,'ST',12, 14),
            ('Emre Belozoglu',      'Turkey',    21, 'CM', 13, 16),
            ('Taribo West',         'Nigeria',   28, 'CB', 13, 13),
            ('Serse Cosmi',         'Italy',     33, 'CM', 11, 11),
            ('Davide Brivio',       'Italy',     25, 'CM', 11, 12),
            # Forwards
            ('Christian Vieri',     'Italy',     28, 'ST', 18, 18),
            ('Ronaldo',             'Brazil',    25, 'ST', 17, 20),  # injured, returning
            ('Hernan Crespo',       'Argentina', 26, 'ST', 17, 17),
            ('Nicola Ventola',      'Italy',     23, 'ST', 13, 14),
        ],
    },
    {
        'name': 'Lazio',
        'short_name': 'Lazio',
        'league': 'Serie A',
        'reputation': 82,
        'budget': 30000000,
        'wage_budget': 1200000,
        'primary_color': '#87CEEB',
        'secondary_color': '#FFFFFF',
        'players': [
            # Goalkeepers
            ('Angelo Peruzzi',      'Italy',     31, 'GK', 15, 15),
            ('Marco Ballotta',      'Italy',     37, 'GK', 13, 13),
            # Defenders
            ('Alessandro Nesta',    'Italy',     25, 'CB', 19, 19),  # left for Milan in 2002
            ('Jaap Stam',           'Netherlands',29,'CB', 18, 18),
            ('Fernando Couto',      'Portugal',  33, 'CB', 14, 14),
            ('Sinisa Mihajlovic',   'Yugoslavia',32,'LB', 15, 15),
            ('Stanislav Varga',     'Slovakia',  29, 'CB', 12, 12),
            ('Demetrio Albertini',  'Italy',     30, 'CM', 15, 15),
            ('Paolo Negro',         'Italy',     30, 'RB', 12, 12),
            # Midfielders
            ('Gaizka Mendieta',     'Spain',     29, 'CM', 15, 15),
            ('Dejan Stankovic',     'Yugoslavia',23,'CM', 15, 16),
            ('Massimo Oddo',        'Italy',     25, 'RB', 13, 14),
            ('Matias Almeyda',      'Argentina', 28, 'CM', 13, 13),
            # Forwards
            ('Simone Inzaghi',      'Italy',     26, 'ST', 16, 16),
            ('Claudio Lopez',       'Argentina', 28, 'ST', 14, 14),
            ('Fabrizio Ravanelli',  'Italy',     33, 'ST', 14, 14),
            ('Bernardo Corradi',    'Italy',     26, 'ST', 13, 14),
            ('Sergio Conceicao',    'Portugal',  26, 'RM', 14, 14),
        ],
    },
    {
        'name': 'Parma',
        'short_name': 'Parma',
        'league': 'Serie A',
        'reputation': 76,
        'budget': 18000000,
        'wage_budget': 850000,
        'primary_color': '#FFFF00',
        'secondary_color': '#003DA5',
        'players': [
            # Goalkeepers
            ('Sebastien Frey',      'France',    22, 'GK', 14, 17),
            ('Pietro Terraneo',     'Italy',     32, 'GK', 11, 11),
            # Defenders
            ('Fabio Cannavaro',     'Italy',     28, 'CB', 17, 17),
            ('Lilian Thuram',       'France',    29, 'RB', 17, 17),  # moved to Juve
            ('Daniele Bonera',      'Italy',     20, 'CB', 12, 16),
            ('Massimo Bresciani',   'Italy',     26, 'CB', 12, 12),
            ('Stefano Fiore',       'Italy',     27, 'CM', 14, 15),
            # Midfielders
            ('Matias Almeyda',      'Argentina', 28, 'CM', 13, 13),
            ('Hidetoshi Nakata',    'Japan',     25, 'AM', 15, 15),
            ('Luigi Sartor',        'Italy',     30, 'CM', 13, 13),
            ('Mauro Camoranesi',    'Argentina', 24, 'RM', 13, 15),
            ('Marco Marchionni',    'Italy',     22, 'RM', 12, 15),
            # Forwards
            ('Adrian Mutu',         'Romania',   22, 'ST', 15, 18),
            ('Marco Di Vaio',       'Italy',     25, 'ST', 15, 16),
            ('Hernan Crespo',       'Argentina', 26, 'ST', 17, 17),  # left for Lazio
            ('Nicola Amoruso',      'Italy',     27, 'ST', 13, 13),
            ('Dino Baggio',         'Italy',     31, 'CM', 13, 13),
            ('Adriano',             'Brazil',    19, 'ST', 14, 18),
        ],
    },
    {
        'name': 'Chievo',
        'short_name': 'Chievo',
        'league': 'Serie A',
        'reputation': 62,
        'budget': 7000000,
        'wage_budget': 450000,
        'primary_color': '#FFD700',
        'secondary_color': '#003DA5',
        'players': [
            # Goalkeepers
            ('Luca Marchegiani',    'Italy',     34, 'GK', 14, 14),
            ('Stefano Sorrentino',  'Italy',     22, 'GK', 11, 14),
            # Defenders
            ('Aimo Diana',          'Italy',     27, 'RB', 13, 13),
            ('Salvatore Lanna',     'Italy',     26, 'CB', 13, 14),
            ('Lorenzo D\'Anna',     'Italy',     30, 'CB', 13, 13),
            ('Federico Fontana',    'Italy',     30, 'CB', 12, 12),
            ('Davide Mandelli',     'Italy',     23, 'LB', 12, 13),
            ('Massimo Gobbi',       'Italy',     22, 'LB', 12, 14),
            # Midfielders
            ('Simone Perrotta',     'Italy',     24, 'CM', 14, 16),
            ('Francesco Maresca',   'Italy',     26, 'CM', 13, 14),
            ('Eugenio Corini',      'Italy',     31, 'CM', 13, 13),
            ('Eriberto',            'Brazil',    26, 'CM', 13, 14),
            ('Gennaro Delvecchio',  'Italy',     23, 'CM', 12, 14),
            # Forwards
            ('Dario Hubner',        'Italy',     35, 'ST', 14, 14),
            ('Massimo Marazzina',   'Italy',     28, 'ST', 14, 14),
            ('Sergio Pellissier',   'Italy',     24, 'ST', 12, 14),
            ('Giovanni Birindelli', 'Italy',     26, 'RM', 12, 12),
            ('Marco Malago',        'Italy',     22, 'AM', 11, 13),
        ],
    },
    {
        'name': 'Udinese',
        'short_name': 'Udinese',
        'league': 'Serie A',
        'reputation': 60,
        'budget': 6000000,
        'wage_budget': 400000,
        'primary_color': '#000000',
        'secondary_color': '#FFFFFF',
        'players': [
            # Goalkeepers
            ('Morgan De Sanctis',   'Italy',     25, 'GK', 14, 16),
            ('Massimo Taibi',       'Italy',     31, 'GK', 12, 12),
            # Defenders
            ('Massimo Carrera',     'Italy',     34, 'CB', 12, 12),
            ('Rino Gattuso',        'Italy',     23, 'CM', 13, 15),  # moved to Milan
            ('Stefano Fiore',       'Italy',     27, 'CM', 14, 14),
            ('Marek Jankulovski',   'Czech Republic',24,'LB',13, 16),
            ('Paolo Poggi',         'Italy',     28, 'RM', 12, 12),
            ('Mirko Gori',          'Italy',     23, 'CB', 12, 13),
            ('Marco Zanchi',        'Italy',     26, 'LB', 12, 12),
            ('Dino Baggio',         'Italy',     31, 'CM', 13, 13),
            # Midfielders
            ('David Pizarro',       'Chile',     22, 'CM', 13, 16),
            ('Thomas Helveg',       'Denmark',   30, 'RB', 14, 14),
            ('Oliver Bierhoff',     'Germany',   33, 'ST', 14, 14),
            ('Robert Prytz',        'Sweden',    24, 'CM', 11, 13),
            # Forwards
            ('Marcio Amoroso',      'Brazil',    27, 'ST', 15, 15),
            ('Filippo Maniero',     'Italy',     31, 'ST', 13, 13),
            ('Vincenzo Iaquinta',   'Italy',     22, 'ST', 12, 16),
            ('Raffaele Ametrano',   'Italy',     27, 'AM', 11, 11),
            ('Cyril Domoraud',      'Ivory Coast',29,'CB', 12, 12),
        ],
    },

    # -------------------------------------------------------------------------
    # BUNDESLIGA
    # -------------------------------------------------------------------------
    {
        'name': 'Bayern Munich',
        'short_name': 'Bayern',
        'league': 'Bundesliga',
        'reputation': 92,
        'budget': 65000000,
        'wage_budget': 2300000,
        'primary_color': '#DC052D',
        'secondary_color': '#0066B2',
        'players': [
            # Goalkeepers
            ('Oliver Kahn',         'Germany',   32, 'GK', 19, 19),
            ('Bernd Dreher',        'Germany',   37, 'GK', 12, 12),
            ('Michael Rensing',     'Germany',   18, 'GK', 10, 15),
            # Defenders
            ('Willy Sagnol',        'France',    24, 'RB', 14, 17),
            ('Bixente Lizarazu',    'France',    31, 'LB', 15, 15),
            ('Thomas Linke',        'Germany',   31, 'CB', 14, 14),
            ('Samuel Kuffour',      'Ghana',     26, 'CB', 14, 14),
            ('Robert Kovac',        'Croatia',   27, 'CB', 14, 15),
            ('Hasan Salihamidzic',  'Bosnia',    25, 'RM', 14, 15),
            # Midfielders
            ('Stefan Effenberg',    'Germany',   33, 'CM', 16, 16),
            ('Jens Jeremies',       'Germany',   28, 'CM', 14, 14),
            ('Mehmet Scholl',       'Germany',   30, 'AM', 15, 15),
            ('Paulo Sergio',        'Brazil',    29, 'AM', 13, 13),
            ('Niko Kovac',          'Croatia',   30, 'CM', 13, 13),
            # Forwards
            ('Claudio Pizarro',     'Peru',      22, 'ST', 14, 17),
            ('Giovane Elber',       'Brazil',    29, 'ST', 17, 17),
            ('Roque Santa Cruz',    'Paraguay',  20, 'ST', 13, 17),
            ('Carsten Jancker',     'Germany',   27, 'ST', 14, 14),
            ('Alexander Zickler',   'Germany',   27, 'ST', 13, 14),
        ],
    },
    {
        'name': 'Borussia Dortmund',
        'short_name': 'Dortmund',
        'league': 'Bundesliga',
        'reputation': 82,
        'budget': 25000000,
        'wage_budget': 1000000,
        'primary_color': '#FDE100',
        'secondary_color': '#000000',
        'players': [
            # Goalkeepers
            ('Jens Lehmann',        'Germany',   32, 'GK', 17, 17),
            ('Roman Weidenfeller',  'Germany',   21, 'GK', 11, 15),
            # Defenders
            ('Jorg Heinrich',       'Germany',   30, 'LB', 13, 13),
            ('Stefan Reuter',       'Germany',   34, 'RB', 13, 13),
            ('Christoph Metzelder', 'Germany',   21, 'CB', 13, 17),
            ('Christian Worns',     'Germany',   30, 'CB', 15, 15),
            ('Dede',                'Brazil',    23, 'LB', 14, 16),
            ('Evanilson',           'Brazil',    25, 'CB', 13, 14),
            # Midfielders
            ('Tomas Rosicky',       'Czech Republic',21,'CM',15, 19),
            ('Torsten Frings',      'Germany',   25, 'CM', 14, 16),
            ('Lars Ricken',         'Germany',   26, 'AM', 13, 13),
            ('Jorg Bohme',          'Germany',   27, 'CM', 13, 13),
            ('Marcio Amoroso',      'Brazil',    27, 'ST', 15, 15),
            ('Stephane Chapuisat',  'Switzerland',32,'ST',13, 13),
            # Forwards
            ('Jan Koller',          'Czech Republic',28,'ST',15, 15),
            ('Amoroso',             'Brazil',    27, 'ST', 17, 17),
            ('Heiko Herrlich',      'Germany',   30, 'ST', 13, 13),
            ('Fredi Bobic',         'Germany',   30, 'ST', 13, 13),
            ('Ewerthon',            'Brazil',    21, 'LM', 13, 16),
        ],
    },
    {
        'name': 'Bayer Leverkusen',
        'short_name': 'Leverkusen',
        'league': 'Bundesliga',
        'reputation': 80,
        'budget': 22000000,
        'wage_budget': 950000,
        'primary_color': '#E32221',
        'secondary_color': '#000000',
        'players': [
            # Goalkeepers
            ('Hans-Jorg Butt',      'Germany',   27, 'GK', 14, 14),
            ('Jorg Remde',          'Germany',   31, 'GK', 11, 11),
            # Defenders
            ('Lucio',               'Brazil',    23, 'CB', 16, 19),
            ('Zivkovic',            'Yugoslavia',26,'CB', 13, 14),
            ('Jens Nowotny',        'Germany',   27, 'CB', 14, 15),
            ('Diego Placente',      'Argentina', 24, 'LB', 13, 15),
            ('Marko Babic',         'Croatia',   21, 'CB', 12, 15),
            # Midfielders
            ('Michael Ballack',     'Germany',   24, 'CM', 18, 18),
            ('Ze Roberto',          'Brazil',    26, 'LM', 15, 15),
            ('Bernd Schneider',     'Germany',   27, 'RM', 14, 14),
            ('Carsten Ramelow',     'Germany',   27, 'CM', 14, 14),
            ('Yildiray Bastürk',    'Turkey',    23, 'AM', 13, 15),
            ('Thomas Brdaric',      'Germany',   26, 'ST', 12, 13),
            # Forwards
            ('Dimitar Berbatov',    'Bulgaria',  20, 'ST', 14, 18),
            ('Ulf Kirsten',         'Germany',   36, 'ST', 14, 14),
            ('Oliver Neuville',     'Germany',   28, 'ST', 14, 15),
            ('Giovanni Elber',      'Brazil',    28, 'ST', 14, 14),
            ('Andriy Voronin',      'Ukraine',   21, 'ST', 12, 15),
        ],
    },
    {
        'name': 'Schalke 04',
        'short_name': 'Schalke',
        'league': 'Bundesliga',
        'reputation': 72,
        'budget': 14000000,
        'wage_budget': 700000,
        'primary_color': '#004D9D',
        'secondary_color': '#FFFFFF',
        'players': [
            # Goalkeepers
            ('Frank Rost',          'Germany',   29, 'GK', 13, 13),
            ('Sascha Rigoni',       'Germany',   25, 'GK', 11, 12),
            # Defenders
            ('Tomasz Waldoch',      'Poland',    31, 'CB', 13, 13),
            ('Sven Vermant',        'Belgium',   27, 'CB', 12, 13),
            ('Niels Oude Kamphuis', 'Netherlands',26,'RB',12, 12),
            ('Jochen Seitz',        'Germany',   27, 'LB', 12, 12),
            ('Slawomir Majak',      'Poland',    25, 'CB', 11, 12),
            ('Christian Pander',    'Germany',   18, 'LB', 10, 14),
            # Midfielders
            ('Gerald Asamoah',      'Germany',   23, 'RM', 14, 15),
            ('Jorg Bohme',          'Germany',   27, 'CM', 13, 14),
            ('Sven Ottke',          'Germany',   28, 'CM', 12, 12),
            ('Levan Kobiashvili',   'Georgia',   24, 'CM', 14, 15),
            ('Marc Wilmots',        'Belgium',   32, 'CM', 14, 14),
            ('Mladen Krstajic',     'Yugoslavia',26,'CB', 13, 14),
            # Forwards
            ('Ebbe Sand',           'Denmark',   28, 'ST', 14, 14),
            ('Victor Agali',        'Nigeria',   24, 'ST', 12, 14),
            ('Mike Hanke',          'Germany',   18, 'ST', 11, 15),
            ('Andreas Moller',      'Germany',   34, 'AM', 14, 14),
            ('Emile Mpenza',        'Belgium',   24, 'ST', 14, 15),
        ],
    },
    {
        'name': 'Werder Bremen',
        'short_name': 'Werder',
        'league': 'Bundesliga',
        'reputation': 70,
        'budget': 12000000,
        'wage_budget': 620000,
        'primary_color': '#1D8348',
        'secondary_color': '#FFFFFF',
        'players': [
            # Goalkeepers
            ('Andreas Reinke',      'Germany',   33, 'GK', 13, 13),
            ('Tim Wiese',           'Germany',   20, 'GK', 11, 15),
            # Defenders
            ('Christian Schulz',    'Germany',   20, 'CB', 11, 14),
            ('Frank Baumann',       'Germany',   26, 'CB', 13, 14),
            ('Naldo',               'Brazil',    19, 'CB', 11, 16),
            ('Paul Stalteri',       'Canada',    26, 'RB', 13, 14),
            ('Bernd Hobsch',        'Germany',   28, 'LB', 12, 12),
            ('Tobias Rau',          'Germany',   20, 'LB', 11, 14),
            # Midfielders
            ('Johann Vogel',        'Switzerland',25,'CM', 14, 15),
            ('Johan Micoud',        'France',    29, 'AM', 15, 15),
            ('Tim Borowski',        'Germany',   21, 'CM', 13, 16),
            ('Nelson Valdez',       'Paraguay',  18, 'ST', 10, 15),
            ('Torsten Frings',      'Germany',   25, 'CM', 14, 15),
            ('Klaus Allofs',        'Germany',   25, 'CM', 12, 13),
            # Forwards
            ('Ailton',              'Brazil',    28, 'ST', 15, 15),
            ('Angelos Charisteas',  'Greece',    22, 'ST', 13, 15),
            ('Miroslav Klose',      'Germany',   23, 'ST', 14, 17),
            ('Fabian Ernst',        'Germany',   24, 'CM', 13, 14),
            ('Markus Daun',         'Germany',   27, 'RM', 12, 12),
        ],
    },
    {
        'name': 'Hamburger SV',
        'short_name': 'Hamburg',
        'league': 'Bundesliga',
        'reputation': 68,
        'budget': 11000000,
        'wage_budget': 580000,
        'primary_color': '#0053A5',
        'secondary_color': '#FFFFFF',
        'players': [
            # Goalkeepers
            ('Stefan Wessels',      'Germany',   26, 'GK', 13, 14),
            ('Oliver Reck',         'Germany',   36, 'GK', 12, 12),
            # Defenders
            ('Daniel van Buyten',   'Belgium',   23, 'CB', 14, 17),
            ('Bastian Reinhardt',   'Germany',   28, 'CB', 13, 13),
            ('Joris Mathijsen',     'Netherlands',22,'CB', 13, 15),
            ('Nico-Jan Hoogma',     'Netherlands',28,'CB', 12, 12),
            ('Stephan Kling',       'Germany',   28, 'LB', 12, 12),
            ('David Jarolim',       'Czech Republic',25,'CM',12, 14),
            # Midfielders
            ('Mehdi Mahdavikia',    'Iran',      26, 'RM', 14, 14),
            ('Stefan Beinlich',     'Germany',   29, 'RM', 12, 12),
            ('Bernd Hollerbach',    'Germany',   32, 'RM', 12, 12),
            ('Torge Hollmann',      'Germany',   23, 'CM', 11, 13),
            ('Christian Rahn',      'Germany',   23, 'AM', 13, 15),
            # Forwards
            ('Sergej Barbarez',     'Bosnia',    29, 'ST', 14, 14),
            ('Emile Mpenza',        'Belgium',   24, 'ST', 14, 15),
            ('Rodolfo Cardoso',     'Argentina', 27, 'ST', 13, 13),
            ('Bernardo Romeo',      'Argentina', 26, 'ST', 13, 14),
            ('Jan Halse',           'Norway',    23, 'LM', 11, 13),
        ],
    },
]
