# The Value Ledger

A football betting database that finds value bets, writes them up in plain
tipster prose, and tracks every one of them in points — winners and losers
alike.

It reads results, shots, expected goals, corners, cards and bookmakers' prices
for every English division down to the National League, every Scottish division
down to League Two, the Bundesliga, Serie A, La Liga, and the two European
competitions. It fits a model to that, compares the model against the best
price on offer at Sky Bet, Bet365, Paddy Power and the rest, and recommends the
bets where the price is wrong — with a stake in points and a reason you can
argue with.

```
Bet of the Week: Stockport County v Barnsley — Stockport County — 2.20 (6/5)
  ★★★★☆  Match result · E2 · 2026-02-14 · 2.25 pts · edge 11%

  The market has not caught up here. Stockport have created plenty and
  finished none of it — 6 goals from 10.7 xG in six games, which usually
  corrects. Barnsley are without Cole and Watters. A fair price of 1.98
  against 2.20 on offer leaves 11% of edge with Sky Bet. Get on at 2.20.
```

---

## What it covers

| Competition | Results & stats | Prices | Real xG |
|---|---|---|---|
| Premier League, Championship, League One, League Two, National League | football-data.co.uk | football-data + odds API | PL only |
| Scottish Premiership, Championship, League One, League Two | football-data.co.uk | football-data + odds API (Premiership) | no |
| Bundesliga, Serie A, La Liga | football-data.co.uk | football-data + odds API | yes |
| Champions League, Europa League | odds API scores / manual | odds API | no |

Where a league has no public xG, the model builds its own from shots and shots
on target, fitted **within that league** — see `vb/models/xg.py`. Where a league
has no live price feed (the Scottish lower divisions, the National League), the
football-data fixtures file still carries opening prices, and `vb template odds`
produces a CSV you can fill in from a coupon in five minutes.

## Markets

Singles: match result, double chance, draw no bet, Asian handicaps (including
quarter lines), over/under on any goal line, team goals, both teams to score,
correct score, clean sheets, total corners, team corners, most corners, total
cards, booking points, player shots, player shots on target, player to be
booked, anytime goalscorer.

Multiples: accumulators across matches, **bet builders within one match** (priced
by simulation, because same-game legs are correlated and multiplying them is
wrong), and long-term outrights — title, top four, promotion, relegation —
priced by playing the rest of the season out several thousand times.

## Using it week to week

**Betting App** — double-click it, and the ledger opens in your browser with
buttons rather than commands: refresh and settle, build this week's card, and
mark which tips you actually backed and at what price.

That last part is the reason the app exists rather than just the report. Two
records are kept and they answer different questions. The **advised** record is
every tip at the price and stake recommended, and says how good the tipping is.
**Your** record is only the bets you struck, at the prices you actually got,
and says how you are doing. Prices move between a card being built and a bet
being placed, and a record that quietly assumes otherwise flatters itself.

Leave the Terminal window that opens running while you use the app; closing it
stops the server.

## Or from the command line

Two files in this folder are double-clickable on a Mac:

* **Betting Tips** — refreshes the data, settles last week's bets, produces this
  week's card and opens the ledger in your browser. This is the one to run.
* **Betting Dashboard** — opens the ledger without fetching anything, for when
  you just want to look at the record.

The same thing from a terminal, if you prefer:

```bash
python3 -m vb weekly            # the whole cycle, then opens the dashboard
python3 -m vb report --open     # just look at the ledger
```

Everything the cycle does is available as its own command — `update`, `tips`,
`settle`, `report` — for when you want one step rather than all of them.

## Getting started

```bash
pip install -r requirements.txt

# 1. Look around first: builds a fake season and a dashboard, no network needed.
python3 -m vb demo

# 2. Then the real thing.  `vb doctor` after any of these says whether it worked.
python3 -m vb update            # results, fixtures and opening prices
python3 -m vb tips --record     # this week's card, written to the ledger
python3 -m vb settle --fetch    # pull fresh results, then grade last week's bets
python3 -m vb report            # rebuild the dashboard
```

`vb demo` writes a dashboard from invented data — the clubs are real and
nothing else is. It exists so you can see the shape of the thing before wiring
up feeds.

For live prices from Sky Bet, Paddy Power and the rest, get a free key from
[the-odds-api.com](https://the-odds-api.com) and:

```bash
export ODDS_API_KEY=...
python3 -m vb update --odds
python3 -m vb doctor            # checks the feeds, the clubs and the key
```

## How it decides

**1. Team strength.** A Dixon-Coles model per league — attack and defence per
club, a home advantage, and a correction for low scores — fitted on results
weighted by recency, and fitted a second time on expected goals. The two are
blended, because goals carry finishing and xG carries everything else, sooner.

**2. Every market from one distribution.** The two expected-goal numbers become
a full distribution over scorelines, and every goal market is read off it. Corners
and cards get their own attack/defence rates with a negative binomial for the
overdispersion real counts show. Player markets come from per-90 rates scaled by
expected minutes, the team's expected workload, and how card-happy the referee is.

**3. What the market thinks.** Each bookmaker's book is devigged on its own —
Shin's method by default, which takes more margin off the outsider than the
favourite, as bookmakers actually build a book. That gives a market probability
to compare against.

**4. Blend, don't override.** The market is the best single forecaster in
football. The model's opinion and the market's are blended on the log-odds
scale, and the weight given to the model rises where prices are soft and falls
where the model has little data to go on. See the notes on `market_blend` in
`config/settings.yaml`.

**5. Edge plus evidence.** A bet needs a positive expectation at the best
available price *and* supporting signals — form, an xG trend, team news, a rest
advantage, a price that has been moving. An edge with no story behind it is
usually a stale price or a club name that failed to match.

**6. Stake.** Quarter-Kelly, capped, in quarter-point steps, with Asian handicap
pushes handled properly.

## Tracking

Every tip goes in the ledger the moment it is generated, at the price and stake
advised. `vb settle` grades them from results. The dashboard shows the running
points total, the ledger with the reasoning behind each bet still attached, and
breakdowns by competition, market and bet type.

It also shows the two numbers that matter more than profit over a small sample:

- **Closing line value** — did we take a better price than the market closed at?
  A tipster who consistently beats the close will end up in front. One who does
  not is being carried by luck.
- **Calibration** — do things the model calls 60% happen 60% of the time? If
  that drifts, the model needs fixing before another bet is placed.

## Backtesting

```bash
python3 -m vb backtest --verbose
```

Replays the season a week at a time. Every model is refitted using only matches
played before the decision date, and every price is read as it stood at the
time — a price taken later is invisible to the engine, which is the one mistake
that makes betting backtests look brilliant and mean nothing.

Read the calibration table it prints before you read the profit. If the model
keeps saying 65% and getting 55%, lower the `market_blend` weights in
`config/settings.yaml` and run it again.

## Commands

| Command | What it does |
|---|---|
| `vb app` | the local web app, with buttons instead of commands |
| `vb weekly` | the whole cycle: refresh, settle, tip, open the dashboard |
| `vb update` | pull results, fixtures, opening prices and xG (`--scores` for same-day results) |
| `vb tips` | this week's card (`--record` to write it to the ledger) |
| `vb settle` | grade everything whose result is in (`--fetch` pulls results first) |
| `vb report` | rebuild the HTML dashboard |
| `vb ledger` | print the bet ledger |
| `vb backtest` | walk-forward replay of the season |
| `vb outlook E0` | simulate the rest of a league |
| `vb template odds\|results\|news` | write a CSV to fill in by hand |
| `vb import odds\|results\|news\|players <file>` | load one back |
| `vb take REF 3.10` | record the price you actually got |
| `vb grade REF won` | settle a player prop or outright by hand |
| `vb apifootball check` | verify the API-Football key and league mapping |
| `vb apifootball probe` | report which endpoints your plan actually serves |
| `vb apifootball injuries` | pull injury lists into team news (paid plans only) |
| `vb suspensions` | infer absences from red cards — no feed needed |
| `vb doctor` | walk the whole pipeline and report what works and what is missing |
| `vb demo` | synthetic season and dashboard, no network needed |

## How quickly results arrive

football-data.co.uk refreshes a couple of times a week, so on a Saturday
morning Friday night's results may not be in yet. Two ways round that:

* `vb settle --fetch` pulls finished scores from the odds API before grading,
  and asks only about the leagues holding open bets — usually three or four
  requests, not fourteen.
* `vb update --scores` does the same across every configured league.

Scores arrive within minutes of full time, and this is also the only automatic
route for Champions and Europa League results, which football-data.co.uk does
not publish at all. The richer feed catches up later with shots, corners and
cards; the fast path only fills in a score where one is missing, so it never
overwrites the better data.

## API-Football (optional, and worth it)

`vb update` and the odds API cover results, prices and fixtures. API-Football
adds the three things neither can: **injury and suspension lists**, per-match
statistics for the divisions where football-data.co.uk publishes little more
than the score, and player-level data.

```bash
cp .env.example .env                   # then paste your key into it
python3 -m vb apifootball check        # 2 requests: verifies the key, maps the leagues
python3 -m vb apifootball injuries     # 1 request per league -> team news
python3 -m vb apifootball fixtures --date 2026-08-29   # 1 request, every league
```

Keys go in `.env`, which is ignored by git and so cannot be committed by
accident. A real environment variable still wins if you prefer one. Never paste
a key into a chat, an issue or a commit — `vb apifootball check` prints no
credential, so its output is safe to share when you want help reading it.

Read the table `check` prints before trusting anything. League ids are numbers,
and a wrong one does not error — it quietly returns a different competition. The
mapping is discovered by matching country and name, every match carries a
confidence score, and near misses are listed so an ambiguous one is visible. If
it gets one wrong, put the right id in `config/leagues.yaml` as `api_football:`
and it will stop guessing.

**Requests are rationed, and the cost is per fixture.** Every result on a given
day costs one request; the statistics for those fixtures cost one *each*. The
free allowance disappears in an afternoon if nothing is counting, so every call
goes through a budget that reads the allowance back from the API's own headers
and stops before it runs out — naming what it did not fetch. `--budget N` caps
a single run.

A sensible weekly rhythm on the free tier:

| When | Command | Cost |
|---|---|---|
| Match day, before betting | `vb apifootball injuries` | ~1 per league |
| Match day, after the games | `vb settle --fetch` | ~1 per league with a bet |
| Occasionally | `vb apifootball fixtures` | 1 per day requested |

Run `vb apifootball probe` before planning around any of it. Free plans
restrict a different set of endpoints than the documentation suggests —
**injuries are not on the free tier**, which is worth knowing before you build a
week around them. The probe costs one request per endpoint and answers it
properly.

Player statistics and per-match shot data are the other expensive calls, and
between them the reason to consider a paid tier.

### Suspensions without any feed

A red card is in the result, so a sending-off can be turned into an absence in
that club's next match with no API at all. `vb update` does this automatically,
and `vb suspensions` runs it on its own.

It cannot name the player — football-data.co.uk records that a team finished
with ten men, not who was dismissed — so the entry reads "a player" and carries
a modest impact. Yellow-card accumulation is deliberately not attempted: it
needs per-player counts that no free feed publishes for these divisions, and a
guess would be worse than the silence.

## Things it needs you to do

Three inputs have no free structured feed worth trusting, and the tool asks for
them rather than pretending:

- **Team news.** Injuries and suspensions move a price more than almost anything
  else. With an API-Football key, `vb apifootball injuries` fills this in
  automatically. Without one, `vb template news` writes a CSV with this
  weekend's clubs already in it. Either way the *importance* of an absence is a
  judgement call the tool leaves at a default — raise it for a talisman.
- **Player data.** Player markets stay switched off until you import minutes,
  shots and cards (an FBref or Sofascore export works).
- **Prices in the smaller leagues.** `vb template odds` for the divisions no
  live feed covers.

## Where it is weakest

Worth knowing before you stake anything:

- **The lower you go, the softer the prices and the worse the model.** The
  National League has the loosest markets and the thinnest data. Those two pull
  in opposite directions, and the blend weights are a guess at the balance —
  check them against a backtest rather than trusting them.
- **Selection bias is real.** We bet where the model disagrees with the market in
  our favour, which is exactly where our own error points the same way. The
  confidence weighting shades for it; it does not remove it. Expect the achieved
  edge to be smaller than the claimed one, and watch the expected-versus-actual
  line on the dashboard.
- **Accumulators multiply model error as fast as they multiply prices.** Each leg
  is shaded before folding, and they are still the weakest bets on the sheet.
- **Bet builder prices are quoted as a target, not a price.** Bookmakers price
  builders with their own correlation model and a fat margin, and no feed
  publishes those prices. The tool tells you the number to hold out for.
- **European ties lean on a prior.** No result has ever been played between a
  Bundesliga club and a National League one, so the gap between divisions is a
  number in `config/settings.yaml`, not something fitted from data.

## Layout

```
config/     leagues.yaml, settings.yaml, aliases.yaml — everything tunable
vb/
  sources/  football-data.co.uk, the-odds-api, understat, openfootball, CSV
  models/   ratings (Dixon-Coles), match markets, corners & cards, players,
            season simulation, correlated match simulation
  market/   devigging and price shopping; edge and staking
  features/ form, xG trends, team news, rest, market drift — the signals
  tips/     selection rules and the write-up
  track/    ledger, settlement, season figures
  report/   the HTML dashboard
  backtest.py, sample.py, cli.py
tests/      run with `python3 -m pytest tests/`
```

## A word about betting

Stakes here are points, never money — one point is one unit of whatever you
decide a unit is. Betting has a negative expected return for almost everybody
who does it, and a model that beats the closing line is a long way from a model
that beats it after the bookmaker restricts your account. Bet only what you can
afford to lose, and if it stops being fun, stop.

GambleAware: [gambleaware.org](https://www.gambleaware.org) · 0808 8020 133
