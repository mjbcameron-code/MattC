# name, nationality, age, reputation, tactical_ability, man_management,
# determination, preferred_formation, preferred_style, wage_pw
#
# 2025/26 real-world managers for Premier League clubs + European top clubs,
# followed by a pool of available managers for AI clubs and replacements.
# The top entries are assigned to PL clubs by reputation rank on game start.
MANAGERS = [
    # =========================================================================
    # PREMIER LEAGUE CLUB MANAGERS (assigned by club reputation at game start)
    # =========================================================================
    # Arsenal (rep=95)
    ('Mikel Arteta',        'Spanish',     43, 95, 18, 16, 19, '4-3-3',   'attacking',  80000),
    # Man City (rep=94)
    ('Pep Guardiola',       'Spanish',     54, 97, 20, 15, 20, '4-3-3',   'attacking',  100000),
    # Liverpool (rep=94)
    ('Arne Slot',           'Dutch',       47, 88, 17, 15, 18, '4-3-3',   'attacking',  70000),
    # Man Utd (rep=92)
    ('Ruben Amorim',        'Portuguese',  40, 84, 17, 16, 18, '3-5-2',   'attacking',  65000),
    # Chelsea (rep=91)
    ('Enzo Maresca',        'Italian',     44, 82, 16, 14, 17, '4-3-3',   'attacking',  60000),
    # Newcastle (rep=86)
    ('Eddie Howe',          'English',     47, 83, 16, 18, 17, '4-3-3',   'attacking',  55000),
    # Aston Villa (rep=89)
    ('Unai Emery',          'Spanish',     54, 92, 18, 16, 19, '4-4-2',   'defensive',  75000),
    # Spurs (rep=87)
    ('Thomas Frank',        'Danish',      52, 80, 15, 17, 17, '4-3-3',   'attacking',  50000),
    # Brighton (rep=82)
    ('Fabian Hurzeler',     'German',      31, 75, 15, 14, 18, '4-3-3',   'attacking',  40000),
    # Nottm Forest (rep=80)
    ('Nuno Espirito Santo', 'Portuguese',  51, 76, 15, 15, 16, '4-4-2',   'defensive',  42000),
    # Fulham (rep=80)
    ('Marco Silva',         'Portuguese',  47, 78, 15, 15, 16, '4-4-2',   'balanced',   45000),
    # West Ham (rep=82)
    ('Graham Potter',       'English',     51, 76, 15, 15, 16, '4-3-3',   'balanced',   45000),
    # Bournemouth (rep=79)
    ('Andoni Iraola',       'Spanish',     43, 78, 15, 16, 17, '4-3-3',   'attacking',  40000),
    # Crystal Palace (rep=79)
    ('Oliver Glasner',      'Austrian',    51, 77, 15, 15, 16, '4-4-2',   'balanced',   40000),
    # Brentford (rep=78)
    ('Nils-Eric Johansson', 'Swedish',     44, 70, 13, 15, 15, '4-3-3',   'balanced',   30000),
    # Everton (rep=77)
    ('Sean Dyche',          'English',     53, 73, 13, 16, 17, '4-4-2',   'defensive',  32000),
    # Wolves (rep=77)
    ('Vitor Pereira',       'Portuguese',  56, 72, 14, 14, 15, '4-4-2',   'defensive',  30000),
    # Leeds (rep=74)
    ('Daniel Farke',        'German',      48, 75, 14, 15, 16, '4-3-3',   'attacking',  35000),
    # Sunderland (rep=68)
    ('Regis Le Bris',       'French',      47, 68, 13, 14, 15, '4-4-2',   'balanced',   25000),
    # Burnley (rep=70)
    ('Scott Parker',        'English',     44, 67, 12, 15, 15, '4-4-2',   'balanced',   25000),
    # =========================================================================
    # AVAILABLE MANAGER POOL (no club — available for hire / AI appointments)
    # =========================================================================
    # High-rep available
    ('Antonio Conte',       'Italian',     56, 94, 19, 14, 20, '3-5-2',   'defensive',  90000),
    ('Jurgen Klopp',        'German',      58, 96, 18, 20, 20, '4-3-3',   'attacking',  95000),
    ('Mauricio Pochettino', 'Argentinian', 53, 86, 17, 18, 18, '4-2-3-1', 'attacking',  70000),
    ('Roberto De Zerbi',    'Italian',     46, 82, 17, 15, 17, '4-3-3',   'attacking',  55000),
    ('Xabi Alonso',         'Spanish',     43, 88, 17, 16, 18, '4-3-3',   'attacking',  70000),
    ('Erik ten Hag',        'Dutch',       55, 80, 16, 15, 16, '4-3-3',   'attacking',  55000),
    ('Carlo Ancelotti',     'Italian',     66, 95, 17, 20, 18, '4-4-2',   'balanced',   90000),
    ('Maurizio Sarri',      'Italian',     57, 82, 17, 12, 16, '4-3-3',   'attacking',  55000),
    ('Brendan Rodgers',     'Northern Irish',52, 78, 15, 17, 16, '4-3-3', 'attacking',  45000),
    ('Frank Lampard',       'English',     47, 71, 13, 16, 16, '4-3-3',   'attacking',  35000),
    ('Steven Gerrard',      'English',     46, 68, 12, 16, 16, '4-3-3',   'attacking',  30000),
    # Good (rep 60-74)
    ('Roger Schmidt',       'German',      57, 74, 15, 13, 15, '4-4-2',   'attacking',  38000),
    ('Julen Lopetegui',     'Spanish',     59, 73, 15, 13, 15, '4-3-3',   'balanced',   37000),
    ('Jonas Eidevall',      'Swedish',     42, 68, 14, 14, 16, '4-3-3',   'attacking',  28000),
    ('Paulo Fonseca',       'Portuguese',  52, 72, 14, 14, 15, '4-3-3',   'attacking',  35000),
    ('Ralph Hasenhuttl',    'Austrian',    58, 71, 14, 15, 16, '4-4-2',   'attacking',  33000),
    ('Chris Wilder',        'English',     57, 70, 13, 16, 17, '3-5-2',   'balanced',   30000),
    ('Patrick Vieira',      'French',      49, 70, 13, 15, 15, '4-3-3',   'attacking',  30000),
    ('Kieran McKenna',      'Irish',       38, 73, 14, 15, 17, '4-3-3',   'attacking',  35000),
    ('Russell Martin',      'English',     39, 67, 13, 14, 15, '4-3-3',   'attacking',  26000),
    ('Wayne Rooney',        'English',     40, 60, 11, 14, 15, '4-4-2',   'attacking',  22000),
    # Average (rep 40-59)
    ('David Moyes',         'Scottish',    62, 66, 13, 16, 15, '4-4-2',   'defensive',  28000),
    ('Steve Cooper',        'Welsh',       45, 65, 13, 14, 15, '4-4-2',   'balanced',   26000),
    ('Lee Carsley',         'Irish',       51, 60, 12, 14, 14, '4-3-3',   'attacking',  22000),
    ('Mark Hughes',         'Welsh',       62, 57, 12, 13, 13, '4-4-2',   'balanced',   20000),
    ('Neil Warnock',        'English',     76, 55, 11, 15, 16, '4-4-2',   'defensive',  18000),
    ('Steve Bruce',         'English',     65, 54, 10, 15, 14, '4-4-2',   'defensive',  17000),
    ('Michael Carrick',     'English',     44, 62, 12, 14, 15, '4-3-3',   'balanced',   24000),
    ('Vincent Kompany',     'Belgian',     39, 72, 14, 15, 17, '4-3-3',   'attacking',  35000),
    ('Ryan Mason',          'English',     33, 50, 10, 13, 13, '4-4-2',   'balanced',   15000),
    ('Darren Ferguson',     'Scottish',    52, 48, 10, 12, 13, '4-4-2',   'balanced',   14000),
    # Lower-rep (rep < 40)
    ('John Terry',          'English',     44, 42,  9, 14, 14, '4-4-2',   'defensive',  12000),
    ('Sol Campbell',        'English',     51, 38,  8, 12, 12, '4-4-2',   'defensive',  10000),
    ('Gary Neville',        'English',     51, 40,  9, 11, 13, '4-4-2',   'balanced',   11000),
    ('Phil Neville',        'English',     49, 35,  8, 11, 12, '4-4-2',   'balanced',    9000),
    ('Paul Scholes',        'English',     51, 36,  9, 10, 12, '4-3-3',   'attacking',   9000),
]
