# Championship Manager — a CM 01/02 tribute

A football management game built in the spirit of the legendary **Championship
Manager 01/02**. Pick a real 2001/02 Premier League club, manage the squad,
set your tactics, play through a full league season with live text commentary,
and wheel and deal in the transfer market.

![season](https://img.shields.io/badge/season-2001%2F02-1b6b3a)

## Features

- **Real 2001/02 squads** — all 20 Premier League clubs with authentic players
  (Henry, Beckham, Owen, Zola, a 16-year-old Rooney at Everton…), each with a
  full Championship Manager-style attribute set (30+ attributes 1–20).
- **Match engine** — minute-by-minute simulation driven by squad strength,
  player attributes, home advantage and tactics, with procedural commentary,
  goals, assists, bookings, sendings-off and substitutions.
- **Live match view** — watch the commentary unfold in real time, or skip
  straight to the result.
- **Tactics** — choose a formation (4-4-2, 4-3-3, 4-5-1, 3-5-2, 4-4-1-1) and a
  mentality, with a visual pitch view and full team selection.
- **Transfer market** — search every player in the database, make bids that the
  AI accepts or rejects based on value and reputation, list and release your own
  players.
- **League & competition** — a full double round-robin fixture list, live league
  table, fixtures/results, top scorers and assists, and a news inbox.

## Tech stack

- Python 3 + Flask
- SQLAlchemy (SQLite database)
- Server-rendered Jinja templates with a classic CM dark-green UI

## Running the game

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the game
python3 app.py

# 3. Open your browser
#    http://localhost:5000
```

On first run the database is created and seeded automatically. Click
**Start New Game**, choose your club, and you're in the manager's chair.

## Project layout

```
app.py                  Flask application & routes
game/
  models.py             SQLAlchemy models (Player, Club, Match, ...)
  engine.py             Match simulation & commentary
  season.py             Fixtures, standings, results
  transfers.py          Transfer market logic
  setup.py              Database seeding & new-game initialisation
data/
  squads.py             Real 2001/02 Premier League squad data
  player_factory.py     Builds full attribute sets from compact definitions
templates/              Jinja2 HTML templates
static/css/style.css    Classic CM-style theme
```

## Notes

This is a fan tribute for personal/educational use. Club names, player names and
likenesses belong to their respective owners. Player attributes are approximate
representations generated from quality ratings, not official data.
