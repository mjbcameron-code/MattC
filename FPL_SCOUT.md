# FPL Scout

A Fantasy Premier League scout that reviews your squad, your transfers, your
chips and your budget, then tells you what to do about them — in the short,
medium and long term.

It reads the public FPL API, projects every player from **underlying data**
rather than the points they have already scored, and writes a self-contained
visual report you open in a browser.

```bash
python3 fpl_scout.py --team-id 1234567 --open
```

Your team ID is the number in your FPL URL:

```
fantasy.premierleague.com/entry/1234567/event/4
                                ^^^^^^^
```

No dependencies beyond the Python standard library, and no account details —
every endpoint it reads is public.

## What it gives you

| View | What it answers |
|---|---|
| **Your squad** | The strongest legal XI, formation, bench order, three captaincy options, and all fifteen players assessed with the numbers behind each verdict |
| **Transfers** | Three plans — safe, balanced, risky — each costed against your bank and free transfers, with hits already deducted |
| **Strategy** | What to do at this deadline, what to build towards over the next month, and what decides your season |
| **Watchlist** | Differentials the field has missed, the template players you *don't* own, and the best options at each position |
| **Fixture ticker** | Eight gameweeks for all twenty clubs, with doubles and blanks marked |
| **Method** | How every number was reached, and what the model cannot see |

## How players are rated

Past points describe what happened. They are a poor guide to what happens
next, so the projection is built from the things that cause points:

- **Expected goals and assists per 90**, scaled by the fixture — each match is
  rated using the attack and defence strength ratings that move with form,
  rather than the static 1–5 difficulty number.
- **Clean sheet odds** from a Poisson model on opponent-adjusted expected goals
  against, blended with the player's own expected goals conceded.
- **Defensive contributions** under the 2026/27 thresholds — 10 clearances,
  blocks, interceptions and tackles for a defender; 12 for a midfielder or
  forward, with ball recoveries counting. Worth two points, capped at two.
- **Saves and bonus**, from each player's own rate of earning them.
- **Minutes**, which scale everything else. A brilliant player who plays
  sixty minutes is worth less than a good one who plays ninety, and this is
  where most projections quietly go wrong.

Season averages hide the difference between a defender who clears the DefCon
threshold most weeks and one who spiked once. So the scout pulls the
**match-by-match history** for your squad and the most defensively active
players in the game, counts how often each actually cleared the bar, and
blends that with the model.

## The 2026/27 rules it encodes

All in [`fpl/rules.py`](fpl/rules.py), so when the rules move the model moves
with them:

- Defensive contribution points: 10 actions for defenders, 12 for midfielders
  and forwards, two points, capped.
- Bonus points system: one BPS per **three** clearances, blocks and
  interceptions (was one per two), reducing the overlap with DefCon.
- Two sets of four chips — Wildcard, Free Hit, Triple Captain, Bench Boost.
  **The first set expires at the Gameweek 19 deadline** and cannot be carried
  over. The chip advice counts down to it.
- Up to five free transfers may be rolled; each extra transfer costs 4 points.
- 15 players, max 3 per club, £100.0m budget.

## Options

```
--team-id N        your FPL entry ID
--gameweek N       gameweek to plan for (default: the next one)
--horizon N        gameweeks to project ahead (default: 5)
--aggression       safe | balanced | aggressive — how much risk to lean towards
--out PATH         where to write the report
--open             open the report when it is written
--demo             run on generated sample data, no network needed
--offline          use cached responses only
--no-deep          skip per-match history: faster, less reliable DefCon rates
```

Responses are cached under `~/.cache/fpl-scout` for fifteen minutes, so
re-running to try a different horizon costs nothing.

### Look around first

```bash
python3 fpl_scout.py --demo --open
```

Runs against a generated season with invented clubs and players. Useful for
seeing the interface, and for testing changes without hammering the API.
Nothing in it is real.

## Reading the advice

Every recommendation comes in three flavours, because "best" depends on what
you are playing for:

- **Safe** — the well-owned move. It cannot really go wrong, and it cannot
  really gain you anything either.
- **Balanced** — the largest projected gain that does not cost a hit.
- **Risky** — differentials under 8% ownership, and a hit where the projection
  clears its cost. In a mini-league this is the only tier that actually gains
  ground: matching the template can only hold your position.

## What it cannot see

It does not read press conferences. It does not know a manager has hinted at
rotation, that a player is being eased back from injury, or that a cup replay
is about to be scheduled. **Check team news before the deadline.**

Doubles and blanks appear here only once the fixture list actually shows them.
An empty ticker means the calendar has not been redrawn yet, not that none are
coming — most are created from the winter onwards.

Projections are estimates. They are honest about their inputs, which is more
than most fantasy advice manages, but they are still estimates.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

32 tests covering the scoring model, fixture maths, squad legality, transfer
budget and club limits, and the report's HTML — including that player names
coming from the API are escaped before they reach the page.

## Layout

```
fpl_scout.py            Command-line entry point
fpl/
  rules.py              The 2026/27 ruleset — every constant the model uses
  api.py                Public API client: caching, retries, no dependencies
  model.py              Normalised Player / Team / Fixture / Squad objects
  loader.py             Fetching, assembling, and per-match DefCon enrichment
  scout.py              Orchestration and the short/medium/long-term narrative
  report.py             The self-contained HTML report
  sample.py             Generated season for tests and the demo
  analysis/
    fixtures.py         Fixture difficulty, doubles and blanks
    projection.py       Expected points from underlying data
    squad.py            Squad review, best XI, captaincy
    transfers.py        Transfer plans at three levels of risk
    chips.py            Chip timing against the GW19 cut-off
tests/test_scout.py     Test suite
```
