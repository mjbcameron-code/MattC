"""Command line: `python3 -m vb <command>`.

    vb demo                  build a synthetic season and a dashboard to look at
    vb update                pull results, fixtures, prices and xG
    vb tips                  this week's card, in tipster prose
    vb settle                grade everything whose result is in
    vb report                write the HTML dashboard
    vb backtest              replay the season, walk-forward

Run `vb <command> --help` for the options on any of them.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import backtest as backtest_mod
from .config import (CACHE_DIR, DB_PATH, enabled_leagues, league as get_league,
                     load_leagues, load_settings)
from .db import session
from .report import dashboard
from .sources import footballdata, manual, understat
from .tips.select import build_tipsheet
from .track import ledger, metrics, settle

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
GREEN, RED, BLUE = "\033[32m", "\033[31m", "\033[34m"


def _leagues(args) -> list[str]:
    if getattr(args, "leagues", None):
        return [code.strip().upper() for code in args.leagues.split(",")]
    return [lg.code for lg in enabled_leagues()]


def _season(args) -> str:
    return getattr(args, "season", None) or load_settings().get("report.season", "2025/26")


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_init(args) -> int:
    with session(args.db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM leagues").fetchone()[0]
    print(f"Database ready at {args.db or DB_PATH} with {count} competitions configured.")
    return 0


def cmd_demo(args) -> int:
    from .sample import generate_all

    with session(args.db) as conn:
        print("Generating a synthetic season (this is fake data — see vb/sample.py)…")
        result = generate_all(conn, season=_season(args))
        played = sum(r["played"] for r in result.values())
        print(f"  {played} matches, {sum(r['scheduled'] for r in result.values())} fixtures ahead")
    with session(args.db) as conn:
        sheet = build_tipsheet(conn, days=args.days, season=_season(args))
        ledger.record_tipsheet(conn, sheet)
        print(f"  {len(sheet.all_tips)} tips written to the ledger")
    with session(args.db) as conn:
        path = dashboard.write(conn, args.out, sheet=sheet, synthetic=True)
    print(f"\nDashboard: {path}")
    print("Open it in a browser. Everything on it is invented — run `vb update` for real data.")
    return 0


def cmd_update(args) -> int:
    season = _season(args)
    codes = _leagues(args)
    seasons = footballdata.recent_seasons(args.history, season)
    totals = {"results": 0, "fixtures": 0, "prices": 0, "xg": 0}
    problems: list[str] = []

    with session(args.db) as conn:
        for code in codes:
            if args.fixtures_only:
                break
            league = load_leagues()[code]
            if league.football_data:
                for season_label in seasons:
                    try:
                        n = footballdata.load_season(conn, code, season_label,
                                                     force=args.force)
                        totals["results"] += n
                        print(f"  {code} {season_label}: {n} matches")
                    except Exception as exc:            # noqa: BLE001 — reported, not swallowed
                        problems.append(f"{code} {season_label}: {exc}")
            if league.understat and not args.no_xg:
                try:
                    n = understat.load_season(conn, code, season, force=args.force)
                    totals["xg"] += n
                    print(f"  {code}: xG attached to {n} matches")
                except Exception as exc:                # noqa: BLE001
                    problems.append(f"{code} xG: {exc}")

        if not args.no_fixtures:
            try:
                counts = footballdata.load_fixtures(conn, season, codes)
                totals["fixtures"] = sum(counts.values())
                print(f"  fixtures: {totals['fixtures']} upcoming with prices "
                      f"({', '.join(sorted(counts)) or 'none'})")
            except Exception as exc:                    # noqa: BLE001
                problems.append(f"fixtures: {exc}")

        # A key that is set is a key that is meant to be used. It stays skippable
        # with --no-odds, because each league costs a request against a monthly
        # allowance, but leaving it behind a flag meant a configured key sat
        # unused and nobody could tell.
        import os

        use_odds = not args.no_odds and bool(os.environ.get("ODDS_API_KEY"))
        if args.odds and not os.environ.get("ODDS_API_KEY"):
            problems.append("--odds was given but ODDS_API_KEY is not set")
        if use_odds:
            from .sources import oddsapi

            # Only ask about leagues that actually have a game coming up.
            with_fixtures = {r["league_code"] for r in conn.execute(
                "SELECT DISTINCT league_code FROM matches WHERE status = 'scheduled' "
                "AND kickoff BETWEEN datetime('now') AND datetime('now', '+8 days')")}
            targets = [c for c in codes
                       if load_leagues()[c].odds_api
                       and (not with_fixtures or c in with_fixtures)]
            if not targets:
                print("  live odds: no league has a fixture in the next week")
            for code in targets:
                try:
                    events, stored = oddsapi.load_league_odds(
                        conn, code, season, force=args.force)
                    totals["prices"] += stored
                    print(f"  {code}: {events} events, {stored} live prices")
                except Exception as exc:                # noqa: BLE001
                    problems.append(f"{code} odds: {exc}")
            if oddsapi.QUOTA:
                print(f"  odds API: {oddsapi.quota_summary()}")

        if args.scores:
            totals["scores"] = _fetch_scores(conn, codes, season, problems)

    with session(args.db) as conn:
        from .features.suspensions import derive_suspensions

        suspended = derive_suspensions(conn)
        if suspended:
            print(f"  {suspended} suspension(s) inferred from recent red cards")

    print(f"\n{totals['results']} results, {totals['fixtures']} fixtures, "
          f"{totals['prices']} live prices, {totals['xg']} xG rows"
          + (f", {totals['scores']} recent scores." if args.scores else "."))
    if problems:
        # Group by the reason rather than listing every league separately.
        grouped: dict[str, list[str]] = {}
        for line in problems:
            label, _, reason = line.partition(": ")
            grouped.setdefault(reason or line, []).append(label)
        print(f"\n{len(problems)} source(s) could not be read:")
        for reason, labels in grouped.items():
            if len(labels) == 1:
                print(f"  - {labels[0]}: {reason}")
            else:
                shown = ", ".join(labels[:6])
                more = f" and {len(labels) - 6} more" if len(labels) > 6 else ""
                print(f"  - {reason}")
                print(f"    affects {shown}{more}")
        if any("proxy" in r or "no such host" in r for r in grouped):
            print("  A file can also be downloaded by hand and dropped into "
                  f"{CACHE_DIR}.")
    return 0


def _fetch_scores(conn, codes: list[str], season: str, problems: list[str]) -> int:
    """Pull recent finished scores for the given leagues.

    One request per league, so the caller decides which leagues are worth
    spending a request on.
    """
    from .sources import oddsapi

    total = 0
    for code in codes:
        league = load_leagues().get(code)
        if not league or not league.odds_api:
            continue
        try:
            got = oddsapi.load_scores(conn, code, season)
            total += got
            if got:
                print(f"  {code}: {got} finished result(s) in")
        except oddsapi.MissingApiKey as exc:
            # The same message once, not once per league.
            problems.append(str(exc))
            break
        except Exception as exc:                        # noqa: BLE001
            problems.append(f"could not fetch {code} scores: {exc}")
    return total


def cmd_tips(args) -> int:
    with session(args.db) as conn:
        sheet = build_tipsheet(
            conn, days=args.days, leagues=_leagues(args) if args.leagues else None,
            season=_season(args), include_outrights=not args.no_outrights,
        )
        if args.json:
            print(json.dumps([t.__dict__ for t in sheet.all_tips], default=str, indent=2))
        else:
            _print_sheet(sheet)
        if args.record:
            counts = ledger.record_tipsheet(conn, sheet)
            print(f"\nRecorded: {counts or 'nothing new'}")
    return 0


def cmd_why(args) -> int:
    """Account for every quoted price: what became a bet, and what stopped it.

    A card with nothing on it from a division looks the same whether the
    engine judged the prices fair or never saw a price at all. This tells the
    two apart.
    """
    from .config import load_leagues
    from .market.value import Trace
    from .tips.select import choose_singles, gather

    names = {code: league.name for code, league in load_leagues().items()}
    with session(args.db) as conn:
        trace = Trace()
        candidates, _, _ = gather(
            conn, days=args.days,
            leagues=_leagues(args) if args.leagues else None, trace=trace)
        choose_singles(candidates, trace=trace)

        codes = trace.leagues()
        if args.leagues:
            wanted = set(_leagues(args))
            codes = [c for c in codes if c in wanted]
        if not codes:
            print("No fixtures in the window at all. Run `vb update` first.")
            return 1

        print(f"\n{BOLD}WHY — the last {args.days} days of fixtures{RESET}")
        for code in codes:
            rows = trace.rows(code)
            tipped = dict(rows).get("tipped", 0)
            print(f"\n{BOLD}{names.get(code, code)}{RESET} "
                  f"{DIM}({trace.total(code)} prices considered, "
                  f"{tipped} tipped){RESET}")
            for reason, count in rows:
                mark = "->" if reason == "tipped" else "  "
                print(f"  {mark} {count:5d}  {reason}")
            setup = trace.weight(code)
            if setup:
                print(f"{DIM}     model weight {setup['weight_low']:.0%}"
                      f"–{setup['weight_high']:.0%} "
                      f"(typically {setup['weight_mid']:.0%}) on "
                      f"{setup['seen_low']:.0f}–{setup['seen_high']:.0f} "
                      f"matches per club{RESET}")
            for edge, label in trace.near_misses(code):
                print(f"{DIM}     {edge:+6.1%}  {label}{RESET}")
    return 0


def _print_sheet(sheet) -> None:
    print(f"\n{BOLD}THE CARD — week {sheet.week_ref}{RESET}")
    print(f"{DIM}{sheet.fixtures_scanned} fixtures priced, {sheet.candidates_found} "
          f"prices with an edge, {len(sheet.all_tips)} bets advised, "
          f"{sheet.total_stake:g} pts staked{RESET}\n")
    if not sheet.all_tips:
        print("Nothing worth backing. That is a result in itself — no bet is a bet.\n")
        return
    for tip in sheet.all_tips:
        print(f"{BOLD}{tip.headline}{RESET}")
        print(f"  {tip.stars}  {tip.market} · {tip.league_code} · {tip.event_date}"
              f" · {BLUE}{tip.stake_pts:g} pt{'s' if tip.stake_pts != 1 else ''}{RESET}"
              f" · edge {tip.edge:.0%}")
        for line in _wrap(tip.body, 88):
            print(f"  {line}")
        print()


def _wrap(text: str, width: int) -> list[str]:
    import textwrap

    return textwrap.wrap(text, width) or [""]


def cmd_explain(args) -> int:
    """Show the full workings behind one fixture's prices.

    The engine's strongest opinions are the ones it throws away: an edge over
    `max_edge` is binned as a data fault, unexamined, every week. Sometimes
    that is right — a stale price, a mis-mapped club — and sometimes it is the
    one genuine call on the card. Nothing decided which, because the workings
    were never visible. This prints them.
    """
    from datetime import datetime

    from .market.odds import best_prices, consensus_fair, latest_quotes
    from .market.value import blend, confidence_weight
    from .models.fixture import ModelBank, build_fixture

    settings = load_settings()
    with session(args.db) as conn:
        like = f"%{args.team}%"
        find = ("SELECT m.*, h.name AS home_name, a.name AS away_name "
                "FROM matches m "
                "JOIN teams h ON h.id = m.home_id "
                "JOIN teams a ON a.id = m.away_id "
                "WHERE (h.name LIKE ? OR a.name LIKE ?) "
                "AND m.status = 'scheduled' ")
        now = datetime.now().isoformat(timespec="seconds")
        # Only fixtures that have not kicked off. "Scheduled" is not the same
        # thing: a match whose result has not been ingested keeps that status
        # indefinitely and, being the earliest, sorts to the front — so without
        # this the command answers about last week's game.
        row = conn.execute(find + "AND m.kickoff >= ? ORDER BY m.kickoff LIMIT 1",
                           (like, like, now)).fetchone()
        if row is None:
            stale = conn.execute(
                find + "AND m.kickoff < ? ORDER BY m.kickoff DESC LIMIT 1",
                (like, like, now)).fetchone()
            if stale is not None:
                print(f"No upcoming fixture for '{args.team}'.\n"
                      f"{stale['home_name']} v {stale['away_name']} on "
                      f"{stale['kickoff'][:10]} has already kicked off but is "
                      f"still marked as not played — its result never arrived, "
                      f"so it will not settle and the model has not learned "
                      f"from it. Run `vb update` to bring results in.")
            else:
                print(f"No upcoming fixture found for '{args.team}'.")
            return 1

        bank = ModelBank(conn, as_of=datetime.now())
        fixture = build_fixture(conn, row, bank)
        if fixture is None:
            print("No model for that fixture yet — not enough matches on file.")
            return 1

        league = get_league(fixture.league_code)
        weight = confidence_weight(
            settings.market_blend(league.tier), fixture.matches_seen,
            float(settings.get("model.confidence_k", 8.0)))
        exchanges = list(settings.get("bookmakers.exchanges", []) or [])
        aggregates = list(settings.get("bookmakers.aggregates", []) or [])
        unbettable = set(exchanges) | set(aggregates)
        sharp = exchanges + aggregates + ["pinnacle"]

        print(f"\n{BOLD}{fixture.label}{RESET} — {league.name}, "
              f"{fixture.kickoff[:16].replace('T', ' ')}")
        print(f"{DIM}model fitted on {fixture.matches_seen} matches per club; "
              f"it gets {weight:.0%} of the say against the market{RESET}")

        groups = conn.execute(
            "SELECT DISTINCT market, line FROM odds "
            "WHERE match_id = ? AND is_closing = 0 ORDER BY market",
            (fixture.match_id,)).fetchall()
        if not groups:
            print("\nNo prices on file for this fixture.")
            return 1

        for group in groups:
            market, line = group["market"], group["line"]
            if args.market and market != args.market:
                continue
            quotes = latest_quotes(conn, fixture.match_id, market, line)
            if not quotes:
                continue
            fair = consensus_fair(quotes, prefer_books=sharp)
            bettable = [q for q in quotes if q.bookmaker not in unbettable]
            best = best_prices(bettable) if bettable else {}
            title = market + (f" {line:g}" if line is not None else "")
            print(f"\n  {BOLD}{title}{RESET}")
            print(f"  {'selection':<14}{'model':>8}{'market':>9}{'blend':>9}"
                  f"{'best':>8}  {'book':<14}{'edge':>8}")
            for selection in sorted({q.selection for q in quotes}):
                subject, _, sel = selection.rpartition("|")
                model_prob = fixture.probability(market, sel, line,
                                                 subject or None)
                market_prob = fair.get(selection)
                quote = best.get(selection)
                blended = (blend(model_prob, market_prob, weight)
                           if model_prob is not None else None)
                edge = (blended * quote.price - 1
                        if blended is not None and quote else None)
                print(f"  {selection:<14}"
                      f"{_pct(model_prob):>8}{_pct(market_prob):>9}"
                      f"{_pct(blended):>9}"
                      f"{(f'{quote.price:.2f}' if quote else '—'):>8}  "
                      f"{(quote.bookmaker if quote else '—'):<14}"
                      f"{(f'{edge:+.1%}' if edge is not None else '—'):>8}")
            print(f"\n  {DIM}every price on file:{RESET}")
            by_book: dict[str, list[str]] = {}
            for q in sorted(quotes, key=lambda q: q.bookmaker):
                mark = "*" if q.bookmaker in unbettable else " "
                by_book.setdefault(f"{q.bookmaker}{mark}", []).append(
                    f"{q.selection} {q.price:.2f}")
            for book, prices in by_book.items():
                print(f"    {DIM}{book:<16}{'  '.join(prices)}{RESET}")
            print(f"    {DIM}* not a price you can take — reference only{RESET}")
    return 0


def _pct(value) -> str:
    return "—" if value is None else f"{value:.1%}"


def cmd_prices(args) -> int:
    """Fair prices for a day's fixtures, for when no price feed is available.

    Some leagues have no odds feed at all, and sometimes a feed is simply
    unreachable. The model still has an opinion, so this prints what we make
    each market — and, more usefully, the price you would need to be offered
    before backing it.

    The required price carries a deliberate margin. Every other route through
    this system blends the model with the market before staking anything,
    because the market is the better forecaster and the bets we like are
    exactly the ones where our own error flatters us. With no market to blend
    against, that correction has to come from somewhere, so the model's
    probability is shaded and a value margin added on top.
    """
    from datetime import datetime, timedelta

    from .models.fixture import ModelBank, build_fixture

    shade = float(args.shade)
    margin = float(args.margin)
    day = args.date or (datetime.now() + timedelta(days=1)).date().isoformat()

    with session(args.db) as conn:
        sql = ("SELECT * FROM matches WHERE match_date = ?"
               + (" AND league_code IN (%s)" % ",".join("?" * len(_leagues(args)))
                  if args.leagues else ""))
        params = [day] + (_leagues(args) if args.leagues else [])
        rows = conn.execute(sql + " ORDER BY league_code, kickoff", params).fetchall()
        if not rows:
            print(f"No fixtures loaded for {day}.")
            return 1

        bank = ModelBank(conn, as_of=datetime.fromisoformat(day + "T00:00:00"))
        print(f"\n{BOLD}Fair prices — {day}{RESET}")
        print(f"{DIM}Model probability shaded by {shade:.0%}, then {margin:.0%} of value "
              f"required. Back only at the 'need' price or bigger.{RESET}")
        current = None
        for row in rows:
            fixture = build_fixture(conn, row, bank, with_players=False,
                                    with_signals=not args.quiet)
            if fixture is None:
                continue
            if row["league_code"] != current:
                current = row["league_code"]
                print(f"\n{BOLD}{load_leagues()[current].name}{RESET}")
            quality = _rating_quality(bank, fixture)
            print(f"\n  {BOLD}{fixture.label}{RESET}  {fixture.kickoff[11:16]}"
                  f"   xG {fixture.probs.lam_home:.2f} – {fixture.probs.lam_away:.2f}"
                  + (f"   {DIM}{quality}{RESET}" if quality else ""))
            print(f"    {'market':34}{'model':>8}{'fair':>8}{'need':>8}")
            for label, market, selection, line in (
                (fixture.home, "h2h", "home", None),
                ("Draw", "h2h", "draw", None),
                (fixture.away, "h2h", "away", None),
                ("Over 2.5 goals", "totals", "over", 2.5),
                ("Under 2.5 goals", "totals", "under", 2.5),
                ("Both teams to score", "btts", "yes", None),
                (f"{fixture.home} or draw", "double_chance", "1x", None),
                (f"{fixture.away} or draw", "double_chance", "x2", None),
            ):
                probability = fixture.probability(market, selection, line)
                if not probability:
                    continue
                fair = 1 / probability
                need = fair / shade * (1 + margin)
                print(f"    {label[:33]:34}{probability:>7.1%}{fair:>8.2f}{need:>8.2f}")
            if not args.quiet and fixture.signals:
                for signal in sorted(fixture.signals, key=lambda x: -x.strength)[:3]:
                    print(f"    {DIM}· {signal.text}{RESET}")
    return 0


def _rating_quality(bank, fixture) -> str:
    """Flag a fixture whose rating had to be carried up from another division."""
    notes = []
    for side, team_id in (("home", fixture.home_id), ("away", fixture.away_id)):
        _, _, source = bank.rating(fixture.league_code, team_id)
        if source != fixture.league_code:
            name = fixture.home if side == "home" else fixture.away
            notes.append(f"{name} rated from {source}")
    return "; ".join(notes)


def cmd_suspensions(args) -> int:
    from .features.suspensions import derive_suspensions

    with session(args.db) as conn:
        written = derive_suspensions(conn)
    print(f"{written} suspension(s) recorded from red cards in recent matches.")
    return 0


def cmd_settle(args) -> int:
    with session(args.db) as conn:
        if args.fetch:
            # Only ask about leagues we actually have money on — each league
            # costs an API request, and most weeks that is three or four rather
            # than all fourteen.
            open_leagues = [r["league_code"] for r in conn.execute(
                "SELECT DISTINCT league_code FROM bets WHERE status = 'pending' "
                "AND league_code IS NOT NULL")]
            if not open_leagues:
                print("No open bets, so nothing to fetch.")
            else:
                problems: list[str] = []
                print(f"Fetching results for {', '.join(sorted(open_leagues))}…")
                _fetch_scores(conn, open_leagues, _season(args), problems)
                for line in problems:
                    print(f"  {line}")
        counts = settle.settle_bets(conn)
        summary = metrics.summarise(conn)
    if counts:
        print("Settled: " + ", ".join(f"{n} {status}" for status, n in sorted(counts.items())))
    else:
        print("Nothing new to settle.")
    colour = GREEN if summary.pnl >= 0 else RED
    print(f"Season: {colour}{summary.pnl:+.2f} pts{RESET} from {summary.settled} bets "
          f"({summary.roi:+.1%} ROI, {summary.strike_rate:.0%} strike rate, "
          f"{summary.pending} open)")
    return 0


def cmd_report(args) -> int:
    with session(args.db) as conn:
        sheet = None
        if not args.no_tips:
            sheet = build_tipsheet(conn, days=args.days, season=_season(args),
                                   include_outrights=False)
        path = dashboard.write(conn, args.out, sheet=sheet, synthetic=args.synthetic)
    print(f"Dashboard written to {path}")
    if getattr(args, "open", False):
        import webbrowser

        webbrowser.open(path.resolve().as_uri())
    return 0


def cmd_weekly(args) -> int:
    """The whole cycle: refresh, settle last week, tip this week, open the ledger.

    The individual commands exist because each one is sometimes wanted alone.
    This is the one to run when what you actually want is "bring it up to date
    and show me".
    """
    steps = [
        ("Refreshing results, fixtures and prices", cmd_update,
         {"leagues": None, "season": None, "history": args.history, "odds": False,
          "no_odds": args.no_odds, "scores": False, "no_fixtures": False,
          "fixtures_only": False, "no_xg": False, "force": False}),
        ("Settling anything whose result is in", cmd_settle,
         {"fetch": not args.no_odds, "season": None}),
    ]
    for title, func, extra in steps:
        print(f"\n{BOLD}{title}…{RESET}")
        func(argparse.Namespace(db=args.db, **extra))

    print(f"\n{BOLD}This week's card{RESET}")
    tips_args = argparse.Namespace(
        db=args.db, days=args.days, leagues=None, season=None,
        record=not args.dry_run, no_outrights=False, json=False)
    cmd_tips(tips_args)

    print(f"\n{BOLD}Building the dashboard{RESET}")
    return cmd_report(argparse.Namespace(
        db=args.db, out=args.out, days=args.days, season=None, no_tips=False,
        synthetic=False, open=not args.no_open))


def cmd_prune(args) -> int:
    """Clear unsettled advice — for when the engine that produced it was wrong."""
    from .track.ledger import drop_open_bets, find_duplicates

    with session(args.db) as conn:
        if args.duplicates:
            groups = find_duplicates(conn)
            if not groups:
                print("No duplicates on the record.")
                return 0
            extra = [ref for group in groups for ref in group["refs"][1:]]
            print(f"{len(groups)} bet(s) recorded more than once; "
                  f"removing {len(extra)} copy(ies):")
            for group in groups:
                print(f"  {group['selection'][:50]}  {', '.join(group['refs'])}")
            print(f"\nRemoved {drop_open_bets(conn, refs=extra)}.")
            return 0
        if args.backtest:
            # Replays used to run in place, leaving their invented bets in the
            # ledger — settled, so the ordinary prune will not touch them.
            rows = conn.execute(
                "SELECT COUNT(*) FROM bets WHERE ref LIKE 'BT%-%'").fetchone()[0]
            if not rows:
                print("No backtest bets on the record.")
                return 0
            if not args.yes:
                print(f"{rows} bet(s) left behind by a backtest would be "
                      f"removed. Real advice is never touched — these are the "
                      f"ones with a BT reference. Re-run with --yes to do it.")
                return 0
            conn.execute("DELETE FROM bet_legs WHERE bet_id IN "
                         "(SELECT id FROM bets WHERE ref LIKE 'BT%-%')")
            conn.execute("DELETE FROM bets WHERE ref LIKE 'BT%-%'")
            print(f"Removed {rows} backtest bet(s) from the ledger.")
            return 0
        open_count = conn.execute(
            "SELECT COUNT(*) FROM bets WHERE status = 'pending'").fetchone()[0]
        if not args.yes:
            print(f"{open_count} unsettled bet(s) would be removed"
                  + (f" (recorded before {args.before})" if args.before else "")
                  + ".\nSettled bets are never touched. Re-run with --yes to do it.")
            return 0
        print(f"Removed {drop_open_bets(conn, before=args.before)} unsettled bet(s).")
    return 0


def cmd_app(args) -> int:
    """Run the local web app."""
    try:
        from .web.app import serve
    except ImportError:
        print("Flask is not installed. Run:  pip3 install -r requirements.txt")
        return 1
    serve(db_path=args.db, port=args.port, open_browser=not args.no_open)
    return 0


def cmd_ledger(args) -> int:
    with session(args.db) as conn:
        rows = dashboard.ledger_rows(conn, limit=args.limit)
        summary = metrics.summarise(conn)
    print(f"{'REF':22}{'DATE':12}{'SELECTION':38}{'PRICE':>7}{'STAKE':>7}"
          f"{'RESULT':>10}{'PTS':>9}")
    for row in rows:
        colour = GREEN if (row["pnl"] or 0) > 0 else (RED if (row["pnl"] or 0) < 0 else "")
        pnl = f"{row['pnl']:+.2f}" if row["pnl"] is not None else "—"
        print(f"{row['ref'][:21]:22}{row['date']:12}{row['selection'][:37]:38}"
              f"{row['price']:>7.2f}{row['stake']:>7.2f}{row['status_label']:>10}"
              f"{colour}{pnl:>9}{RESET}")
    print(f"\n{summary.pnl:+.2f} pts | ROI {summary.roi:+.1%} | {summary.settled} settled "
          f"| {summary.pending} open")
    return 0


def cmd_backtest(args) -> int:
    """Replay a season against a throwaway copy of the database.

    Never against the real one. The replay records its invented bets in the
    ledger and settles them, so run in place it would leave hundreds of them
    sitting among real advice — and, because a bet already on the record is
    refused, every later run would quietly do nothing and reprint the first
    one's figures.
    """
    import shutil
    import tempfile
    from pathlib import Path

    source = Path(args.db) if args.db else DB_PATH
    if not source.exists():
        print(f"No database at {source}. Run `vb update` first.")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "backtest.db"
        shutil.copy(source, scratch)
        return _run_backtest(scratch, args)


def _run_backtest(db_path, args) -> int:
    with session(db_path) as conn:
        def progress(cursor, n, total):
            print(f"  {cursor.date()}  {n:2d} tips  ({total} so far)", flush=True)

        # "all" walks every season on file. One season is around 180 bets, and
        # at these prices that is not enough to tell a losing engine from a
        # break-even one — the sample is the limiting factor, not the model.
        season = None if (args.season or "").lower() == "all" else _season(args)
        result = backtest_mod.run(
            conn, season=season,
            leagues=_leagues(args) if args.leagues else None,
            warmup_weeks=args.warmup, progress=progress if args.verbose else None,
        )
    if result.note:
        print(f"\n{BOLD}Backtest: nothing to test{RESET}\n  {result.note}")
        return 1
    # Headline on bets advised at a price a bookmaker was seen to offer. A
    # builder is quoted at a target computed from our own fair price and
    # settled at it, so its profit and loss restates the model rather than
    # testing it — shading its legs raised the demanded price and "improved"
    # 158 bets without one of them changing.
    s = result.priced if result.priced.settled else result.summary
    unpriced = result.summary.settled - result.priced.settled
    print(f"\n{BOLD}Backtest {result.first_date} → {result.last_date}{RESET}")
    print(f"  {result.weeks} weeks, {s.settled} bets at a real price, "
          f"{s.staked:.1f} pts staked")
    if unpriced:
        print(f"  {DIM}{unpriced} more were advised at a target price no book "
              f"was seen to offer ({result.summary.pnl - s.pnl:+.2f} pts). They "
              f"are in the table below but not in these figures — a price we "
              f"set ourselves cannot measure us.{RESET}")
    colour = GREEN if s.pnl >= 0 else RED
    print(f"  {colour}{s.pnl:+.2f} pts{RESET}  ROI {s.roi:+.1%} "
          f"± {s.roi_stderr:.1%}  strike {s.strike_rate:.1%}"
          f"  avg price {s.average_odds:.2f}")
    if s.roi_stderr and abs(s.roi) < 2 * s.roi_stderr:
        # Long odds make profit and loss a very noisy measure. Saying so is the
        # difference between "this loses money" and "this cannot yet be told
        # apart from break-even", which are different findings entirely.
        low, high = s.roi - 2 * s.roi_stderr, s.roi + 2 * s.roi_stderr
        print(f"  {DIM}That ROI is inside the noise: anything from {low:+.0%} "
              f"to {high:+.0%} fits this many bets at these prices. "
              f"Calibration and CLV are the numbers to read.{RESET}")
    # How many bets the CLV covers, not just the average. Closing line value is
    # only measurable on a single: a multiple has no one closing price to
    # compare against. So a card full of accumulators can show a healthy CLV
    # over the third of it that is singles while the rest quietly loses.
    print(f"  CLV {s.clv_average:+.2%} (beat the close {s.clv_beat_rate:.0%} "
          f"of the time, measured on {s.clv_measured} of {s.settled} settled)")
    print(f"  expected {s.expected_pnl:+.1f} pts against {s.pnl:+.1f} actual"
          f"  ·  worst drawdown {s.max_drawdown:.1f} pts")
    if result.by_type:
        print(f"\n  {'bet type':>12}{'bets':>7}{'staked':>9}{'pts':>9}{'ROI':>8}")
        for row in sorted(result.by_type, key=lambda r: r["pnl"]):
            tint = GREEN if row["pnl"] >= 0 else RED
            print(f"  {row['name']:>12}{row['bets']:>7}{row['staked']:>9.1f}"
                  f"{tint}{row['pnl']:>9.2f}{RESET}{row['roi']:>+8.1%}")

    print(f"\n  {'model said':>12}{'bets':>7}{'predicted':>11}{'actual':>9}")
    for row in result.calibration:
        print(f"  {row['range']:>12}{row['bets']:>7}{row['predicted']:>11.1%}"
              f"{row['actual']:>9.1%}")
    return 0


def cmd_calibrate(args) -> int:
    """Fit the over-confidence correction, and report it on unseen bets.

    A correction fitted and judged on the same games always looks good, so the
    record is split by date: the earlier half fits the line, the later half is
    never touched by it and is the only number worth reading.
    """
    import shutil
    import tempfile
    from pathlib import Path

    from . import calibrate

    source = Path(args.db) if args.db else DB_PATH
    if not source.exists():
        print(f"No database at {source}. Run `vb update` first.")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "calibrate.db"
        shutil.copy(source, scratch)
        with session(scratch) as conn:
            season = None if (args.season or "all").lower() == "all" \
                else _season(args)
            print("Replaying the record. This takes a few minutes…")
            result = backtest_mod.run(conn, season=season,
                                      warmup_weeks=args.warmup)
            if result.note:
                print(f"\n{result.note}")
                return 1
            graded = calibrate.settled_bets(conn)

    if len(graded) < 60:
        print(f"Only {len(graded)} graded bets. Too few to fit anything "
              f"honest — run `--season all`, or wait for more football.")
        return 1

    half = len(graded) // 2
    train = [(p, won) for _, p, won in graded[:half]]
    holdout = [(p, won) for _, p, won in graded[half:]]

    fitted = calibrate.fit(train)
    print(f"\n{BOLD}Calibration{RESET}")
    print(f"  fitted on {len(train)} bets, held back {len(holdout)}")
    print(f"  corrected_logit = {fitted.slope:.3f} x logit(p) "
          f"{fitted.intercept:+.3f}")

    before_e, before_a, before_z = calibrate.gap(holdout)
    corrected = [(calibrate.apply(p, fitted.slope, fitted.intercept), won)
                 for p, won in holdout]
    after_e, after_a, after_z = calibrate.gap(corrected)

    print(f"\n  {BOLD}On the half it never saw{RESET}")
    print(f"  {'':<12}{'expected':>10}{'actual':>9}{'z':>8}")
    print(f"  {'as it is':<12}{before_e:>10.1f}{before_a:>9.0f}{before_z:>8.2f}")
    print(f"  {'corrected':<12}{after_e:>10.1f}{after_a:>9.0f}{after_z:>8.2f}")

    if abs(after_z) < abs(before_z):
        print(f"\n  The correction helps out of sample. To use it, put this in "
              f"config/settings.yaml under `model:`\n")
        print(f"    calibration:\n      slope: {fitted.slope:.3f}\n"
              f"      intercept: {fitted.intercept:.3f}\n")
        print(f"  {DIM}Expect far fewer tips afterwards, and treat that as the "
              f"point rather than a fault: an edge that only existed because "
              f"the probability was too high should stop being advised.{RESET}")
    else:
        print(f"\n  It does not help out of sample — {after_z:+.2f} against "
              f"{before_z:+.2f}. Leave the identity in place; a wrong "
              f"correction is worse than none.")
    return 0


def cmd_outlook(args) -> int:
    from .models.ratings import fit_league
    from .models.season import simulate_season

    with session(args.db) as conn:
        model = fit_league(conn, args.league)
        if model is None:
            print(f"Not enough played matches for {args.league}.")
            return 1
        outlook = simulate_season(conn, model, _season(args), simulations=args.sims)
        if outlook is None:
            print("No results loaded for that season.")
            return 1
        print(f"\n{BOLD}{load_leagues()[args.league].name} — {args.sims:,} simulated seasons"
              f"{RESET}\n")
        print(f"{'club':28}{'pld':>5}{'pts':>5}{'exp':>8}{'title':>8}{'top 4':>8}{'rel':>8}")
        for name, expected, title, relegation in outlook.table():
            team_id = next(t for t, n in outlook.teams.items() if n == name)
            print(f"{name:28}{outlook.played[team_id]:>5}{outlook.current_points[team_id]:>5}"
                  f"{expected:>8.1f}{title:>8.1%}"
                  f"{outlook.probability_position(team_id, 4):>8.1%}{relegation:>8.1%}")
    return 0


def cmd_template(args) -> int:
    with session(args.db) as conn:
        writer = {
            "odds": manual.odds_template,
            "results": manual.results_template,
            "news": manual.news_template,
        }.get(args.kind)
        if writer is None:
            print(f"Unknown template {args.kind!r}")
            return 1
        path = writer(conn, args.out, days=args.days,
                      leagues=_leagues(args) if args.leagues else None)
    print(f"Template written to {path} — fill it in and run `vb import {args.kind} {path}`")
    return 0


def cmd_import(args) -> int:
    with session(args.db) as conn:
        loaders = {
            "odds": lambda: manual.load_odds(conn, args.path, _season(args)),
            "results": lambda: manual.load_results(conn, args.path, _season(args)),
            "news": lambda: manual.load_team_news(conn, args.path),
            "players": lambda: manual.load_player_stats(conn, args.path),
        }
        loader = loaders.get(args.kind)
        if loader is None:
            print(f"Unknown import type {args.kind!r}")
            return 1
        print(f"Imported {loader()} rows from {args.path}")
    return 0


def cmd_take(args) -> int:
    with session(args.db) as conn:
        ok = ledger.set_price_taken(conn, args.ref, args.price, args.stake)
    print("Updated." if ok else f"No bet with reference {args.ref!r}.")
    return 0 if ok else 1


def cmd_grade(args) -> int:
    with session(args.db) as conn:
        ok = settle.settle_bet_manually(conn, args.ref, args.status)
    print("Graded." if ok else f"Could not grade {args.ref!r} as {args.status!r}.")
    return 0 if ok else 1


def cmd_apifootball(args) -> int:
    """Check the API-Football key and league mapping, or pull from it."""
    from .sources import apifootball as af

    try:
        client = af.Client(budget=af.Budget(max_this_run=args.budget), via=args.via)
    except af.MissingKey as exc:
        print(exc)
        return 1

    season = _season(args)
    try:
        return _apifootball_action(args, client, season)
    except af.BudgetExhausted as exc:
        print(f"{RED}{exc}{RESET}")
        print(f"\n{client.budget.describe()}")
        return 1
    except af.ApiFootballError as exc:
        # These carry the API's own words and what to do about them. A stack
        # trace on top of that helps nobody.
        print(f"{RED}{exc}{RESET}")
        return 1


def _apifootball_action(args, client, season: str) -> int:
    from .sources import apifootball as af

    with session(args.db) as conn:
        if args.action == "check":
            report = af.check(conn, client, season)
            print(f"\n{BOLD}API-Football{RESET}")
            print(f"  shopfront          : {report['shopfront']}")
            print(f"  key in use         : {report['key']}")
            if report.get("key_warning"):
                print(f"  {RED}{report['key_warning']}{RESET}")
            if not report.get("ok"):
                for line in report["errors"]:
                    print(f"  {RED}{line}{RESET}")
                return 1
            print(f"  plan               : {report.get('plan')} "
                  f"({'active' if report.get('plan_active') else 'inactive'})")
            print(f"  requests today     : {report.get('requests_today')} of "
                  f"{report.get('requests_limit')}")
            print(f"\n  {'league':8}{'matched to':34}{'id':>8}{'season':>8}{'score':>7}")
            for code, match in report["leagues"].items():
                colour = GREEN if match.confident else RED
                print(f"  {code:8}{colour}{(match.api_name or '— no match')[:33]:34}{RESET}"
                      f"{str(match.api_id or '—'):>8}{str(match.season or '—'):>8}"
                      f"{match.score:>7.2f}")
                if match.note:
                    print(f"         {DIM}{match.note}{RESET}")
                for name, other_id, score in match.alternatives:
                    print(f"         {DIM}also considered: {name} (id {other_id}, "
                          f"{score:.2f}){RESET}")
            if report["unmatched"]:
                print(f"\n  {RED}{len(report['unmatched'])} league(s) need checking: "
                      f"{', '.join(report['unmatched'])}{RESET}")
                print("  Put the right id in config/leagues.yaml as `api_football:` "
                      "to override.")
            else:
                print(f"\n  {GREEN}every league mapped confidently{RESET}")
            print(f"\n  {report.get('budget', '')}")
            return 0

        if args.action == "fixtures":
            counts = af.load_fixtures(conn, client, season, date=args.date,
                                      codes=_leagues(args) if args.leagues else None)
            print(f"fixtures/results written: {sum(counts.values())} "
                  f"({', '.join(f'{k} {v}' for k, v in sorted(counts.items())) or 'none'})")
        elif args.action == "injuries":
            counts = af.load_injuries(
                conn, client, season,
                codes=_leagues(args) if args.leagues else None)
            total = sum(counts.values())
            print(f"team news written: {total} absences across "
                  f"{sum(1 for v in counts.values() if v)} leagues")
            for code, n in sorted(counts.items()):
                if n:
                    print(f"   {code}: {n}")
        elif args.action == "probe":
            results = af.probe_plan(conn, client, season)
            print(f"\n{BOLD}What this plan serves{RESET}\n")
            for endpoint, info in results.items():
                mark = {"available": GREEN + "yes" + RESET,
                        "denied": RED + "no " + RESET}.get(info["status"],
                                                           DIM + "?  " + RESET)
                print(f"  {mark}  {endpoint:22}{DIM}{info['buys']}{RESET}")
                if info["status"] != "available":
                    print(f"          {DIM}{info['detail'][:130]}{RESET}")
        elif args.action == "stats":
            pending = af.matches_needing_statistics(
                conn, limit=args.limit,
                codes=_leagues(args) if args.leagues else None)
            if not pending:
                print("No played matches are both missing shot data and known to "
                      "this feed. Run `apifootball fixtures` first — the fixture "
                      "ids it stores are what makes this possible.")
            else:
                print(f"{len(pending)} matches missing shot data; "
                      f"one request each.")
                filled = af.load_statistics(conn, client, pending)
                print(f"filled in {filled}")
        print(f"\n{client.budget.describe()}")
        for skipped in client.budget.skipped:
            print(f"  {RED}skipped:{RESET} {skipped}")
    return 0


def cmd_doctor(args) -> int:
    """Walk the whole pipeline and report what works, what is thin, what is broken.

    Answers one question — is this thing actually ready to tip — rather than
    leaving it to be inferred from a series of separate commands.
    """
    from datetime import datetime, timedelta

    from .models.fixture import ModelBank, build_fixture
    from .models.ratings import fit_league

    ok, warn, bad = f"{GREEN}ok{RESET}  ", f"{BLUE}thin{RESET}", f"{RED}none{RESET}"
    problems: list[str] = []

    with session(args.db) as conn:
        print(f"{BOLD}Database{RESET} {args.db or DB_PATH}")
        rows = conn.execute(
            "SELECT league_code, COUNT(*) AS n, "
            "SUM(status = 'played') AS played, SUM(status = 'scheduled') AS ahead, "
            "MAX(match_date) AS latest FROM matches GROUP BY league_code"
        ).fetchall()
        if not rows:
            print(f"\n  {RED}No matches loaded.{RESET} Run `vb update` — nothing else "
                  "works until there is football in here.")
            return 1

        # ---- 1. what is loaded ------------------------------------------
        print(f"\n{BOLD}1. Data{RESET}")
        print(f"  {'league':8}{'played':>8}{'ahead':>7}{'latest':>12}{'priced':>8}"
              f"{'shots':>7}{'xG':>6}")
        by_league = {}
        for row in rows:
            code = row["league_code"]
            priced = conn.execute(
                "SELECT COUNT(DISTINCT o.match_id) FROM odds o JOIN matches m "
                "ON m.id = o.match_id WHERE m.league_code = ? AND m.status = 'scheduled'",
                (code,)).fetchone()[0]
            shots = conn.execute(
                "SELECT COUNT(*) FROM matches WHERE league_code = ? AND hst IS NOT NULL",
                (code,)).fetchone()[0]
            xg = conn.execute(
                "SELECT COUNT(*) FROM matches WHERE league_code = ? AND home_xg IS NOT NULL",
                (code,)).fetchone()[0]
            by_league[code] = {"played": row["played"] or 0, "ahead": row["ahead"] or 0,
                               "priced": priced, "shots": shots}
            print(f"  {code:8}{row['played'] or 0:>8}{row['ahead'] or 0:>7}"
                  f"{(row['latest'] or '—'):>12}{priced:>8}{shots:>7}{xg:>6}")

        stale = [c for c, d in by_league.items() if d["ahead"] == 0]
        if stale:
            problems.append(
                f"no fixtures ahead for {', '.join(sorted(stale))} — `vb update` pulls "
                "the fixtures file, which only reaches about a week out")

        # ---- 2. club identity -------------------------------------------
        print(f"\n{BOLD}2. Clubs{RESET}")
        counts = conn.execute(
            "SELECT t.id, t.name, COUNT(m.id) AS n FROM teams t LEFT JOIN matches m "
            "ON m.home_id = t.id OR m.away_id = t.id GROUP BY t.id"
        ).fetchall()
        singles = [r for r in counts if r["n"] <= 1]
        established = [r for r in counts if r["n"] > 5]
        print(f"  {len(counts)} clubs, "
              f"{conn.execute('SELECT COUNT(*) FROM team_aliases').fetchone()[0]} spellings")
        if singles:
            from .repo import token_similarity

            print(f"  {len(singles)} club(s) with almost no matches. That is either "
                  f"a name that failed to match, or a club new to the data:")
            suspected = []
            for row in singles[:12]:
                # Naming the club it was probably meant to be is the whole point:
                # the fix is a line in aliases.yaml, and that line needs both names.
                twin, score = None, 0.0
                for other in established:
                    similarity = token_similarity(row["name"], other["name"])
                    if similarity > score:
                        twin, score = other, similarity
                if twin is not None and score >= 0.5:
                    suspected.append(row)
                    print(f"    {RED}{row['name']:28}{RESET} probably the same club as "
                          f"{twin['name']} ({twin['n']} matches, {score:.0%} alike)")
                else:
                    print(f"    {row['name']:28} no obvious match — it may simply be "
                          "newly promoted")
            if suspected:
                problems.append(
                    f"{len(suspected)} club(s) look like duplicates from a spelling "
                    "mismatch; add them to config/aliases.yaml")
            else:
                print(f"  {DIM}None of these resembles an existing club, so they are "
                      f"most likely newly promoted rather than misspelled.{RESET}")
        else:
            print(f"  {GREEN}no duplicates detected{RESET}")

        # ---- 3. can the model fit? ---------------------------------------
        print(f"\n{BOLD}3. Model{RESET}")
        print(f"  {'league':8}{'fits':>7}{'home adv':>10}{'goals/game':>12}  note")
        fittable = 0
        for code in sorted(by_league):
            model = fit_league(conn, code)
            if model is None:
                print(f"  {code:8}{bad:>16}{'':>10}{'':>12}  too few results to fit")
                continue
            import math
            # A club with few games in this division is only a problem if it has
            # nowhere to borrow a rating from. Promotion churn is normal and is
            # already handled by rating such clubs from the division below.
            unsupported = []
            for team_id, played in (model.matches_per_team or {}).items():
                if played >= 6:
                    continue
                elsewhere = conn.execute(
                    "SELECT COUNT(*) FROM matches WHERE (home_id = ? OR away_id = ?) "
                    "AND status = 'played' AND league_code != ?",
                    (team_id, team_id, code)).fetchone()[0]
                if elsewhere < 6:
                    unsupported.append(team_id)
            mark = warn if unsupported else ok
            note = (f"{len(unsupported)} club(s) new to the data entirely"
                    if unsupported else "")
            print(f"  {code:8}{mark:>16}{model.home_adv:>10.3f}"
                  f"{math.exp(model.base) * 2:>12.2f}  {note}")
            fittable += 1
        if not fittable:
            problems.append("no league has enough results to fit — run `vb update`")

        # ---- 4. does the pipeline produce anything? ----------------------
        print(f"\n{BOLD}4. Pipeline{RESET}")
        as_of = datetime.now()
        upcoming = conn.execute(
            "SELECT * FROM matches WHERE status = 'scheduled' AND kickoff >= ? "
            "AND kickoff <= ? ORDER BY kickoff",
            (as_of.isoformat(), (as_of + timedelta(days=7)).isoformat()),
        ).fetchall()
        print(f"  fixtures in the next 7 days      {len(upcoming)}")
        if not upcoming:
            problems.append("no fixtures in the next week, so there is nothing to tip")
        else:
            bank = ModelBank(conn, as_of=as_of)
            # Fitting is the slow part, so a large card is sampled rather than
            # priced in full. Say so, or the sample size reads as a failure count.
            sample = upcoming[:60]
            modelled = priced_fixtures = 0
            for row in sample:
                fixture = build_fixture(conn, row, bank, with_players=False,
                                        with_signals=False)
                if fixture is None:
                    continue
                modelled += 1
                if conn.execute("SELECT 1 FROM odds WHERE match_id = ? LIMIT 1",
                                (row["id"],)).fetchone():
                    priced_fixtures += 1
            checked = f" (of {len(sample)} checked)" if len(sample) < len(upcoming) else ""
            print(f"  the model can price              {modelled}{checked}")
            print(f"  and bookmakers' prices are in    {priced_fixtures}{checked}")
            if modelled < len(sample):
                problems.append(
                    f"{len(sample) - modelled} fixture(s) could not be modelled — "
                    "usually a league with too few results loaded")
            if modelled and not priced_fixtures:
                problems.append(
                    "fixtures are modelled but carry no prices, so no edge can be "
                    "measured — check that `vb update` reached the fixtures file")

        news = conn.execute(
            "SELECT COUNT(*) FROM team_news WHERE added_at >= date('now', '-14 days')"
        ).fetchone()[0]
        print(f"  team news in the last fortnight  {news}"
              + ("" if news else f"   {BLUE}(none — see below){RESET}"))

        from .track.ledger import find_duplicates

        duplicates = find_duplicates(conn)
        if duplicates:
            print(f"  {RED}{len(duplicates)} bet(s) on the record twice{RESET} — "
                  "run `vb prune --duplicates`")
            problems.append(f"{len(duplicates)} duplicate bet(s) would double-count "
                            "your record; `vb prune --duplicates` clears them")

        settled = conn.execute(
            "SELECT COUNT(*) FROM bets WHERE status != 'pending'").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM bets WHERE status = 'pending'").fetchone()[0]
        print(f"  bets recorded                    {settled + pending} "
              f"({pending} open, {settled} settled)")

        # ---- 5. optional extras -------------------------------------------
        print(f"\n{BOLD}5. Optional{RESET}")
        players = conn.execute("SELECT COUNT(*) FROM player_stats").fetchone()[0]
        print(f"  player records   {players}"
              + ("" if players else "   player markets stay off until some are imported"))
        import os
        if os.environ.get("ODDS_API_KEY"):
            live = conn.execute(
                "SELECT COUNT(DISTINCT bookmaker) AS books, COUNT(*) AS n FROM odds "
                "WHERE source = 'odds-api'"
            ).fetchone()
            from .sources import oddsapi
            state = (f"set — {live['n']} prices from {live['books']} book(s) via the API"
                     if live["n"] else
                     f"{BLUE}set, but no prices have come from it yet{RESET}")
            print(f"  odds API key     {state}")
            if oddsapi.QUOTA:
                print(f"                   {oddsapi.quota_summary()}")
        else:
            print("  odds API key     not set")
        print(f"  API-Football key {'set' if os.environ.get('API_FOOTBALL_KEY') else 'not set'}")

        # ---- verdict -------------------------------------------------------
        print(f"\n{BOLD}Verdict{RESET}")
        if problems:
            for problem in problems:
                print(f"  {RED}·{RESET} {problem}")
            print("\n  Fix those and run `vb doctor` again.")
            return 1
        print(f"  {GREEN}Everything the tipping needs is in place.{RESET} "
              "Run `vb tips` for a card.")
        if not news:
            print(f"  {DIM}No team news loaded. Suspensions come from red cards "
                  f"automatically; injuries need `vb template news` or a paid "
                  f"API-Football plan.{RESET}")
    return 0


# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vb", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", help="path to the database file")
    subs = parser.add_subparsers(dest="command", required=True)

    def add(name, func, help_text):
        sub = subs.add_parser(name, help=help_text)
        sub.set_defaults(func=func)
        return sub

    add("init", cmd_init, "create the database")

    demo = add("demo", cmd_demo, "build a synthetic season and a dashboard")
    demo.add_argument("--days", type=int, default=7)
    demo.add_argument("--season")
    demo.add_argument("--out")

    update = add("update", cmd_update, "pull results, fixtures, prices and xG")
    update.add_argument("--leagues", help="comma separated codes, e.g. E0,E1,SC0")
    update.add_argument("--season")
    update.add_argument("--history", type=int, default=3, help="seasons of results")
    update.add_argument("--odds", action="store_true",
                        help="deprecated: live prices are pulled whenever "
                             "ODDS_API_KEY is set")
    update.add_argument("--no-odds", action="store_true",
                        help="skip the live odds API even though a key is set")
    update.add_argument("--scores", action="store_true",
                        help="also pull finished scores from the odds API — far faster "
                             "than waiting for the football-data refresh (1 request "
                             "per league)")
    update.add_argument("--no-fixtures", action="store_true")
    update.add_argument("--fixtures-only", action="store_true",
                        help="skip the results files and refresh only the upcoming "
                             "fixtures and their prices")
    update.add_argument("--no-xg", action="store_true")
    update.add_argument("--force", action="store_true", help="ignore the cache")

    tips = add("tips", cmd_tips, "this week's card")
    tips.add_argument("--days", type=int, default=7)
    tips.add_argument("--leagues")
    tips.add_argument("--season")
    tips.add_argument("--record", action="store_true", help="write them to the ledger")
    tips.add_argument("--no-outrights", action="store_true")
    tips.add_argument("--json", action="store_true")

    cal = add("calibrate", cmd_calibrate,
              "fit the over-confidence correction and test it on unseen bets")
    cal.add_argument("--season", help='a season, or "all" (the default)')
    cal.add_argument("--warmup", type=int, default=8)

    why = add("why", cmd_why,
              "account for every price: what was tipped and what stopped it")
    why.add_argument("--days", type=int, default=7)
    why.add_argument("--leagues")

    explain = add("explain", cmd_explain,
                  "the full workings behind one fixture's prices")
    explain.add_argument("team", help="any part of either club's name")
    explain.add_argument("--market", help="just this market, e.g. h2h")

    prices = add("prices", cmd_prices, "fair prices for a day's fixtures (no odds needed)")
    prices.add_argument("--date", help="YYYY-MM-DD, default tomorrow")
    prices.add_argument("--leagues")
    prices.add_argument("--shade", type=float, default=0.92,
                        help="shade model probabilities by this, for over-confidence")
    prices.add_argument("--margin", type=float, default=0.10,
                        help="value required on top of the shaded price")
    prices.add_argument("--quiet", action="store_true", help="hide the reasoning")

    settle_cmd = add("settle", cmd_settle, "grade everything whose result is in")
    settle_cmd.add_argument("--fetch", action="store_true",
                            help="pull fresh results first, for the leagues holding "
                                 "open bets only")
    settle_cmd.add_argument("--season")

    report = add("report", cmd_report, "write the HTML dashboard")
    report.add_argument("--out")
    report.add_argument("--days", type=int, default=7)
    report.add_argument("--season")
    report.add_argument("--no-tips", action="store_true")
    report.add_argument("--synthetic", action="store_true")
    report.add_argument("--open", action="store_true",
                        help="open the dashboard in your browser when it is built")

    weekly = add("weekly", cmd_weekly,
                 "the whole cycle: refresh, settle, tip, open the dashboard")
    weekly.add_argument("--days", type=int, default=7)
    weekly.add_argument("--history", type=int, default=3)
    weekly.add_argument("--out")
    weekly.add_argument("--dry-run", action="store_true",
                        help="show the card without writing it to the ledger")
    weekly.add_argument("--no-odds", action="store_true")
    weekly.add_argument("--no-open", action="store_true")

    prune = add("prune", cmd_prune, "clear unsettled advice from the record")
    prune.add_argument("--before", help="only those recorded before this timestamp")
    prune.add_argument("--duplicates", action="store_true",
                       help="remove only bets recorded twice, keeping the first")
    prune.add_argument("--backtest", action="store_true",
                       help="remove bets a backtest left in the ledger (BT refs)")
    prune.add_argument("--yes", action="store_true", help="actually do it")

    web = add("app", cmd_app, "run the local web app in your browser")
    web.add_argument("--port", type=int, default=5137)
    web.add_argument("--no-open", action="store_true")

    led = add("ledger", cmd_ledger, "print the bet ledger")
    led.add_argument("--limit", type=int, default=40)

    bt = add("backtest", cmd_backtest, "replay the season, walk-forward")
    bt.add_argument("--leagues")
    bt.add_argument("--season")
    bt.add_argument("--warmup", type=int, default=8, help="weeks of results before tipping")
    bt.add_argument("--verbose", action="store_true")

    outlook = add("outlook", cmd_outlook, "simulate the rest of a season")
    outlook.add_argument("league")
    outlook.add_argument("--season")
    outlook.add_argument("--sims", type=int, default=10000)

    template = add("template", cmd_template, "write a CSV to fill in by hand")
    template.add_argument("kind", choices=["odds", "results", "news"])
    template.add_argument("--out")
    template.add_argument("--days", type=int, default=8)
    template.add_argument("--leagues")

    imp = add("import", cmd_import, "load a CSV you filled in")
    imp.add_argument("kind", choices=["odds", "results", "news", "players"])
    imp.add_argument("path")
    imp.add_argument("--season")

    take = add("take", cmd_take, "record the price you actually got")
    take.add_argument("ref")
    take.add_argument("price", type=float)
    take.add_argument("--stake", type=float)

    grade = add("grade", cmd_grade, "grade a bet by hand (player props, outrights)")
    grade.add_argument("ref")
    grade.add_argument("status", choices=["won", "lost", "void", "half_won", "half_lost"])

    apif = add("apifootball", cmd_apifootball,
               "check the API-Football key and mapping, or pull from it")
    apif.add_argument("action",
                      choices=["check", "probe", "fixtures", "injuries", "stats"],
                      help="check verifies the key and maps the leagues; "
                           "probe reports which endpoints your plan serves")
    apif.add_argument("--season")
    apif.add_argument("--leagues")
    apif.add_argument("--date", help="YYYY-MM-DD, for fixtures")
    apif.add_argument("--budget", type=int, default=40,
                      help="stop after this many requests (default 40)")
    apif.add_argument("--limit", type=int, default=20)
    apif.add_argument("--via", choices=["direct", "rapidapi"],
                      help="force which shopfront the key belongs to, instead of "
                           "letting it be guessed from the key")

    add("doctor", cmd_doctor, "check what is loaded and what is missing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
