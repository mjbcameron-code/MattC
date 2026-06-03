from flask_sqlalchemy import SQLAlchemy
from datetime import date

db = SQLAlchemy()


class League(db.Model):
    __tablename__ = 'leagues'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    country = db.Column(db.String(50), nullable=False)
    level = db.Column(db.Integer, default=1)
    clubs = db.relationship('Club', backref='league', lazy=True)


class Club(db.Model):
    __tablename__ = 'clubs'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    short_name = db.Column(db.String(30))
    league_id = db.Column(db.Integer, db.ForeignKey('leagues.id'))
    reputation = db.Column(db.Integer, default=50)  # 1-100
    budget = db.Column(db.Integer, default=5000000)
    wage_budget = db.Column(db.Integer, default=500000)
    primary_color = db.Column(db.String(7), default='#cc0000')
    secondary_color = db.Column(db.String(7), default='#ffffff')
    players = db.relationship('Player', backref='club', lazy=True)


class Player(db.Model):
    __tablename__ = 'players'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    nationality = db.Column(db.String(50))
    age = db.Column(db.Integer, default=22)
    position = db.Column(db.String(10))       # primary: GK, RB, CB, LB, RM, CM, LM, AM, ST
    positions = db.Column(db.String(50))      # all positions, comma-separated
    club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=True)
    wage = db.Column(db.Integer, default=5000)        # weekly £
    value = db.Column(db.Integer, default=1000000)
    contract_end = db.Column(db.Integer, default=2004) # year
    squad_number = db.Column(db.Integer)
    is_injured = db.Column(db.Boolean, default=False)
    injury_weeks = db.Column(db.Integer, default=0)
    morale = db.Column(db.Integer, default=70)        # 0-100
    is_youth = db.Column(db.Boolean, default=False)
    condition = db.Column(db.Integer, default=100)    # 0-100
    transfer_listed = db.Column(db.Boolean, default=False)
    agent_name = db.Column(db.String(100), default='')
    agent_aggression = db.Column(db.Integer, default=5)   # 1-10; drives how hard they bargain
    release_clause = db.Column(db.Integer, nullable=True)  # auto-accept if bid >= this amount
    # Physical
    acceleration = db.Column(db.Integer, default=10)
    pace = db.Column(db.Integer, default=10)
    stamina = db.Column(db.Integer, default=10)
    strength = db.Column(db.Integer, default=10)
    agility = db.Column(db.Integer, default=10)
    jumping = db.Column(db.Integer, default=10)
    # Technical
    crossing = db.Column(db.Integer, default=10)
    dribbling = db.Column(db.Integer, default=10)
    finishing = db.Column(db.Integer, default=10)
    first_touch = db.Column(db.Integer, default=10)
    heading = db.Column(db.Integer, default=10)
    long_shots = db.Column(db.Integer, default=10)
    marking = db.Column(db.Integer, default=10)
    passing = db.Column(db.Integer, default=10)
    tackling = db.Column(db.Integer, default=10)
    technique = db.Column(db.Integer, default=10)
    # Mental
    aggression = db.Column(db.Integer, default=10)
    anticipation = db.Column(db.Integer, default=10)
    bravery = db.Column(db.Integer, default=10)
    composure = db.Column(db.Integer, default=10)
    concentration = db.Column(db.Integer, default=10)
    creativity = db.Column(db.Integer, default=10)
    decisions = db.Column(db.Integer, default=10)
    determination = db.Column(db.Integer, default=10)
    flair = db.Column(db.Integer, default=10)
    off_the_ball = db.Column(db.Integer, default=10)
    positioning = db.Column(db.Integer, default=10)
    teamwork = db.Column(db.Integer, default=10)
    work_rate = db.Column(db.Integer, default=10)
    # GK specific
    handling = db.Column(db.Integer, default=10)
    reflexes = db.Column(db.Integer, default=10)
    aerial = db.Column(db.Integer, default=10)
    one_on_ones = db.Column(db.Integer, default=10)
    rushing_out = db.Column(db.Integer, default=10)
    # Ability
    current_ability = db.Column(db.Integer, default=100)
    potential_ability = db.Column(db.Integer, default=120)

    def overall_rating(self):
        pos = self.position
        if pos == 'GK':
            attrs = [self.handling, self.reflexes, self.aerial, self.one_on_ones,
                     self.composure, self.concentration, self.decisions]
        elif pos in ('CB', 'RB', 'LB'):
            attrs = [self.tackling, self.marking, self.pace, self.heading,
                     self.concentration, self.composure, self.positioning, self.strength]
        elif pos in ('CM', 'RM', 'LM', 'AM'):
            attrs = [self.passing, self.stamina, self.decisions, self.creativity,
                     self.tackling, self.work_rate, self.first_touch, self.technique]
        else:  # ST, forward
            attrs = [self.finishing, self.pace, self.acceleration, self.dribbling,
                     self.off_the_ball, self.composure, self.first_touch, self.heading]
        return round(sum(attrs) / len(attrs))

    def get_positions_list(self):
        if self.positions:
            return [p.strip() for p in self.positions.split(',')]
        return [self.position]


class Season(db.Model):
    __tablename__ = 'seasons'
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, default=2001)
    name = db.Column(db.String(50))
    matches = db.relationship('Match', backref='season', lazy=True)
    standings = db.relationship('Standing', backref='season', lazy=True)


class Match(db.Model):
    __tablename__ = 'matches'
    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('seasons.id'))
    league_id = db.Column(db.Integer, db.ForeignKey('leagues.id'), nullable=True)
    home_club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'))
    away_club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'))
    match_date = db.Column(db.String(20))      # stored as 'YYYY-MM-DD'
    match_week = db.Column(db.Integer, default=1)
    competition = db.Column(db.String(50), default='League')
    played = db.Column(db.Boolean, default=False)
    home_score = db.Column(db.Integer)
    away_score = db.Column(db.Integer)
    home_club = db.relationship('Club', foreign_keys=[home_club_id])
    away_club = db.relationship('Club', foreign_keys=[away_club_id])
    events = db.relationship('MatchEvent', backref='match', lazy=True,
                              cascade='all, delete-orphan')


class MatchEvent(db.Model):
    __tablename__ = 'match_events'
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('matches.id'))
    minute = db.Column(db.Integer)
    event_type = db.Column(db.String(30))   # goal, yellow_card, red_card, substitution
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=True)
    assist_player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=True)
    club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=True)
    description = db.Column(db.Text)
    player = db.relationship('Player', foreign_keys=[player_id])
    assist_player = db.relationship('Player', foreign_keys=[assist_player_id])
    club = db.relationship('Club', foreign_keys=[club_id])


class Standing(db.Model):
    __tablename__ = 'standings'
    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('seasons.id'))
    league_id = db.Column(db.Integer, db.ForeignKey('leagues.id'))
    club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'))
    played = db.Column(db.Integer, default=0)
    won = db.Column(db.Integer, default=0)
    drawn = db.Column(db.Integer, default=0)
    lost = db.Column(db.Integer, default=0)
    goals_for = db.Column(db.Integer, default=0)
    goals_against = db.Column(db.Integer, default=0)
    points = db.Column(db.Integer, default=0)
    club = db.relationship('Club', foreign_keys=[club_id])

    @property
    def goal_difference(self):
        return self.goals_for - self.goals_against


class PlayerStat(db.Model):
    __tablename__ = 'player_stats'
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'))
    season_id = db.Column(db.Integer, db.ForeignKey('seasons.id'))
    club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'))
    appearances = db.Column(db.Integer, default=0)
    goals = db.Column(db.Integer, default=0)
    assists = db.Column(db.Integer, default=0)
    yellow_cards = db.Column(db.Integer, default=0)
    red_cards = db.Column(db.Integer, default=0)
    player = db.relationship('Player', foreign_keys=[player_id])
    club = db.relationship('Club', foreign_keys=[club_id])


class Transfer(db.Model):
    __tablename__ = 'transfers'
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'))
    from_club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=True)
    to_club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=True)
    fee = db.Column(db.Integer, default=0)
    transfer_date = db.Column(db.String(20))
    status = db.Column(db.String(20), default='pending')  # pending, accepted, rejected
    player = db.relationship('Player', foreign_keys=[player_id])
    from_club = db.relationship('Club', foreign_keys=[from_club_id])
    to_club = db.relationship('Club', foreign_keys=[to_club_id])


class NewsItem(db.Model):
    __tablename__ = 'news_items'
    id = db.Column(db.Integer, primary_key=True)
    game_state_id = db.Column(db.Integer, db.ForeignKey('game_states.id'))
    date = db.Column(db.String(20))
    headline = db.Column(db.String(200))
    body = db.Column(db.Text)
    category = db.Column(db.String(30), default='general')  # result, transfer, injury, general
    read = db.Column(db.Boolean, default=False)


class Suspension(db.Model):
    __tablename__ = 'suspensions'
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'))
    season_id = db.Column(db.Integer, db.ForeignKey('seasons.id'), nullable=True)
    matches_remaining = db.Column(db.Integer, default=1)
    reason = db.Column(db.String(50))  # 'yellow_accumulation', 'red_card'
    player = db.relationship('Player', foreign_keys=[player_id])


class Loan(db.Model):
    """Tracks season-long loan deals (in both directions)."""
    __tablename__ = 'loans'
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'))
    parent_club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=True)
    loan_club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'))
    season_id = db.Column(db.Integer, db.ForeignKey('seasons.id'))
    start_date = db.Column(db.String(20))
    active = db.Column(db.Boolean, default=True)
    player = db.relationship('Player', foreign_keys=[player_id])
    parent_club = db.relationship('Club', foreign_keys=[parent_club_id])
    loan_club = db.relationship('Club', foreign_keys=[loan_club_id])


class ContractNegotiation(db.Model):
    """Tracks DoF ↔ agent contract talks for players at the managed club."""
    __tablename__ = 'contract_negotiations'
    id = db.Column(db.Integer, primary_key=True)
    game_state_id = db.Column(db.Integer, db.ForeignKey('game_states.id'))
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'))
    initiated_by = db.Column(db.String(10), default='dof')   # 'dof' | 'agent'
    status = db.Column(db.String(20), default='active')       # active|accepted|rejected|expired
    dof_wage_offer = db.Column(db.Integer, nullable=True)
    dof_years_offer = db.Column(db.Integer, nullable=True)
    agent_wage_demand = db.Column(db.Integer, nullable=True)
    agent_years_demand = db.Column(db.Integer, nullable=True)
    rounds = db.Column(db.Integer, default=0)
    created_date = db.Column(db.String(20))
    expires_date = db.Column(db.String(20))
    player = db.relationship('Player', foreign_keys=[player_id])


class TransferBid(db.Model):
    """Pending transfer bids where the selling club has made a counter-offer."""
    __tablename__ = 'transfer_bids'
    id = db.Column(db.Integer, primary_key=True)
    game_state_id = db.Column(db.Integer, db.ForeignKey('game_states.id'))
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'))
    selling_club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=True)
    bid_fee = db.Column(db.Integer, default=0)
    counter_fee = db.Column(db.Integer, nullable=True)    # selling club's counter
    status = db.Column(db.String(30), default='club_countered')  # club_countered|rejected
    created_date = db.Column(db.String(20))
    player = db.relationship('Player', foreign_keys=[player_id])
    selling_club = db.relationship('Club', foreign_keys=[selling_club_id])


class Scout(db.Model):
    """A scout employed by the Director of Football to assess players."""
    __tablename__ = 'scouts'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    nationality = db.Column(db.String(50), default='English')
    age = db.Column(db.Integer, default=50)
    judging_ability = db.Column(db.Integer, default=10)    # 1-20
    judging_potential = db.Column(db.Integer, default=10)  # 1-20
    region = db.Column(db.String(30), default='England')   # England|Europe|South America|World
    wage = db.Column(db.Integer, default=2000)
    club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=True)
    assignment_player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=True)
    assignment_region = db.Column(db.String(30), nullable=True)
    assignment_player = db.relationship('Player', foreign_keys=[assignment_player_id])


class ScoutKnowledge(db.Model):
    """The managed club's accumulated scouting knowledge of a player."""
    __tablename__ = 'scout_knowledge'
    id = db.Column(db.Integer, primary_key=True)
    game_state_id = db.Column(db.Integer, db.ForeignKey('game_states.id'))
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'))
    knowledge = db.Column(db.Integer, default=0)          # 0-100
    ca_low = db.Column(db.Integer, nullable=True)
    ca_high = db.Column(db.Integer, nullable=True)
    pa_low = db.Column(db.Integer, nullable=True)
    pa_high = db.Column(db.Integer, nullable=True)
    recommendation = db.Column(db.Text, nullable=True)
    shortlisted = db.Column(db.Boolean, default=False)
    complete = db.Column(db.Boolean, default=False)
    player = db.relationship('Player', foreign_keys=[player_id])


class OwnerDemand(db.Model):
    """A chairman directive that the DoF must fulfil within a deadline."""
    __tablename__ = 'owner_demands'
    id = db.Column(db.Integer, primary_key=True)
    game_state_id = db.Column(db.Integer, db.ForeignKey('game_states.id'))
    demand_type = db.Column(db.String(30))    # sign_position | sell_listed | keep_wage_bill
    target = db.Column(db.String(100))        # position / 'any' / wage threshold str
    description = db.Column(db.Text)
    deadline = db.Column(db.String(20))
    fulfilled = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)


class Manager(db.Model):
    """NPC head coach hired and managed by the Director of Football."""
    __tablename__ = 'managers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    nationality = db.Column(db.String(50), default='English')
    age = db.Column(db.Integer, default=45)
    reputation = db.Column(db.Integer, default=50)        # 0-100
    tactical_ability = db.Column(db.Integer, default=10)  # 1-20
    man_management = db.Column(db.Integer, default=10)    # 1-20
    determination = db.Column(db.Integer, default=10)      # 1-20
    preferred_formation = db.Column(db.String(20), default='4-4-2')
    preferred_style = db.Column(db.String(20), default='balanced')
    wage = db.Column(db.Integer, default=5000)
    contract_end = db.Column(db.Integer, default=2004)
    club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=True)
    satisfaction = db.Column(db.Integer, default=70)      # 0-100 relationship with DoF
    club = db.relationship('Club', foreign_keys=[club_id],
                           backref=db.backref('head_coach', uselist=False))


class GameState(db.Model):
    __tablename__ = 'game_states'
    id = db.Column(db.Integer, primary_key=True)
    managed_club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'))
    current_date = db.Column(db.String(20), default='2001-08-18')
    current_season_id = db.Column(db.Integer, db.ForeignKey('seasons.id'), nullable=True)
    manager_name = db.Column(db.String(100), default='Manager')
    formation = db.Column(db.String(10), default='4-4-2')
    tactic = db.Column(db.String(20), default='Normal')
    created_at = db.Column(db.String(30))
    board_confidence = db.Column(db.Integer, default=50)    # 0-100
    board_target = db.Column(db.String(50), default='Finish Mid-Table')
    board_min_pos = db.Column(db.Integer, default=7)
    board_max_pos = db.Column(db.Integer, default=17)
    is_sacked = db.Column(db.Boolean, default=False)
    managed_club = db.relationship('Club', foreign_keys=[managed_club_id])
    current_season = db.relationship('Season', foreign_keys=[current_season_id])
    news = db.relationship('NewsItem', backref='game_state', lazy=True,
                           cascade='all, delete-orphan')


class Lineup(db.Model):
    __tablename__ = 'lineups'
    id = db.Column(db.Integer, primary_key=True)
    game_state_id = db.Column(db.Integer, db.ForeignKey('game_states.id'))
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'))
    slot = db.Column(db.Integer)   # 1-11 = starters, 12-16 = subs
    position_played = db.Column(db.String(10))
    player = db.relationship('Player', foreign_keys=[player_id])
