#!/usr/bin/env python3
"""FPL Scout — assess your Fantasy Premier League squad and plan your season.

Reads the public Fantasy Premier League API, projects every player from
underlying data rather than past points, and writes a self-contained report
you can open in a browser.

    python3 fpl_scout.py --team-id 1234567
    python3 fpl_scout.py --team-id 1234567 --horizon 6 --open
    python3 fpl_scout.py --demo          # synthetic data, no network needed

Your team ID is the number in your FPL URL:
    fantasy.premierleague.com/entry/1234567/event/4
                                    ^^^^^^^
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from fpl.api import FplApiError, FplClient
from fpl.config import load_team_id, save_team_id
from fpl.loader import load_all
from fpl.report import render
from fpl.scout import Scout


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fpl_scout",
        description="Scout your FPL squad: transfers, captaincy, chips and strategy.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Find your team ID in your FPL URL: /entry/<THIS NUMBER>/event/1",
    )
    parser.add_argument(
        "--team-id", type=int,
        help="your FPL entry (team) ID (remembered after the first run)",
    )
    parser.add_argument(
        "--forget", action="store_true",
        help="clear the remembered team ID and exit",
    )
    parser.add_argument("--gameweek", type=int, help="gameweek to plan for (default: the next one)")
    parser.add_argument(
        "--horizon", type=int, default=5,
        help="how many gameweeks ahead to project (default: 5)",
    )
    parser.add_argument(
        "--aggression", choices=("safe", "balanced", "aggressive"), default="balanced",
        help="how much risk the advice should lean towards (default: balanced)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("fpl-scout-report.html"),
        help="where to write the report (default: fpl-scout-report.html)",
    )
    parser.add_argument("--open", action="store_true", help="open the report when it is written")
    parser.add_argument(
        "--fragment", action="store_true",
        help="omit the html/head/body shell, for embedding in another page",
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="run against generated sample data, with no network access",
    )
    parser.add_argument(
        "--offline", action="store_true",
        help="use only cached API responses, however old",
    )
    parser.add_argument(
        "--no-deep", action="store_true",
        help="skip per-match history (faster, but DefCon rates are less reliable)",
    )
    parser.add_argument("--cache-ttl", type=int, default=900, help="cache lifetime in seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.forget:
        from fpl.config import CONFIG_FILE

        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()
            print(f"Forgot the stored team ID ({CONFIG_FILE}).")
        else:
            print("No team ID was stored.")
        return 0

    # Explicit flag wins, then FPL_TEAM_ID, then whatever was saved last time.
    remembered = False
    if not args.team_id and not args.demo:
        args.team_id = load_team_id()
        remembered = args.team_id is not None

    if not args.demo and not args.team_id:
        print(
            "No team ID given.\n\n"
            "  Run with your own team:   python3 fpl_scout.py --team-id 1234567\n"
            "  Or look around first:     python3 fpl_scout.py --demo\n\n"
            "Your team ID is a plain number, from your FPL URL:\n"
            "  fantasy.premierleague.com/entry/1234567/event/4\n"
            "                                  ^^^^^^^\n"
            "It is remembered after the first run, so you only type it once.\n",
            file=sys.stderr,
        )
        return 2

    if args.horizon < 1 or args.horizon > 15:
        print("--horizon must be between 1 and 15 gameweeks.", file=sys.stderr)
        return 2

    if args.demo:
        from fpl.sample import SampleClient

        client = SampleClient()
        entry_id = 1234567
        print("Running on generated sample data — nothing here is real.")
    else:
        if args.team_id <= 0:
            print("A team ID must be a positive number.", file=sys.stderr)
            return 2
        client = FplClient(ttl_seconds=args.cache_ttl, offline=args.offline)
        entry_id = args.team_id
        source = " (remembered)" if remembered else ""
        print(f"Fetching Fantasy Premier League data for team {entry_id}{source}…")

    try:
        loaded = load_all(client, entry_id, args.gameweek, deep=not args.no_deep)
    except FplApiError as error:
        print(f"\nCould not load the data: {error}\n", file=sys.stderr)
        if "not found" in str(error).lower() or "team ID" in str(error):
            from fpl.config import CONFIG_FILE, load_team_id as _stored

            if not args.demo and _stored() == entry_id and CONFIG_FILE.exists():
                CONFIG_FILE.unlink()
            print(
                f"No FPL team with the ID {entry_id} exists.\n\n"
                "Check the number in your FPL URL while logged in:\n"
                "  fantasy.premierleague.com/entry/1234567/event/4\n"
                "                                  ^^^^^^^\n"
                "Then run again with --team-id, or clear the stored one with --forget.",
                file=sys.stderr,
            )
        else:
            if not args.demo:
                save_team_id(entry_id)
            print(
                "This looks like a network problem rather than a bad team ID, so the ID\n"
                "has been remembered anyway. Try again in a moment, or use --offline to\n"
                "fall back on cached data.",
                file=sys.stderr,
            )
        return 1

    if not args.demo:
        saved_to = save_team_id(entry_id)
        if saved_to:
            print(f"  Remembered this team ID — future runs need no arguments.")

    squad = loaded.squad
    if squad:
        print(
            f"  {squad.team_name} — {squad.manager_name}\n"
            f"  GW{loaded.gameweek} · £{squad.bank_m:.1f}m banked · "
            f"{squad.free_transfers} free transfer(s) · {len(squad.picks)} players"
        )
    if loaded.enriched:
        print(f"  Checked match-by-match history for {loaded.enriched} players")

    report = Scout(horizon=args.horizon, aggression=args.aggression).run(loaded)
    report.is_sample = args.demo

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(report, fragment=args.fragment), encoding="utf-8")
    print(f"\nReport written to {args.out.resolve()}")

    _summarise(report)

    if args.open:
        webbrowser.open(args.out.resolve().as_uri())
    return 0


def _summarise(report) -> None:
    """A short version of the findings, for the terminal."""
    review = report.review
    if review:
        print(f"\n  Formation {review.formation} · projected "
              f"{review.projected_next_gw:.0f} pts in GW{report.gameweek}")
        for option in review.captains:
            print(f"  Captain ({option.tier}): {option.player_name} — "
                  f"{option.projection:.1f}/match, {option.ownership:.1f}% owned")
        for warning in review.warnings[:3]:
            print(f"  ! {warning}")

    for plan in report.plans:
        hit = f" (−{plan.hit_cost} hit)" if plan.hits else ""
        print(f"  Transfers ({plan.tier}): {plan.headline} → {plan.net_gain:+.1f} pts{hit}")

    urgent = [c for c in report.chips if c.available and c.urgency in ("Use soon", "Expiring")]
    for chip in urgent:
        print(f"  Chip: {chip.label} — {chip.urgency.lower()}")


if __name__ == "__main__":
    raise SystemExit(main())
