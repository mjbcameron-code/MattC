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
    parser.add_argument("--team-id", type=int, help="your FPL entry (team) ID")
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

    if not args.demo and not args.team_id:
        print(
            "No team ID given.\n\n"
            "  Run with your own team:   python3 fpl_scout.py --team-id 1234567\n"
            "  Or look around first:     python3 fpl_scout.py --demo\n\n"
            "Your team ID is the number in your FPL URL:\n"
            "  fantasy.premierleague.com/entry/1234567/event/4\n",
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
        client = FplClient(ttl_seconds=args.cache_ttl, offline=args.offline)
        entry_id = args.team_id
        print(f"Fetching Fantasy Premier League data for team {entry_id}…")

    try:
        loaded = load_all(client, entry_id, args.gameweek, deep=not args.no_deep)
    except FplApiError as error:
        print(f"\nCould not load the data: {error}\n", file=sys.stderr)
        print(
            "If this is a network problem, try again in a moment. If the team ID is wrong,\n"
            "check the number in your FPL URL. Use --offline to fall back on cached data.",
            file=sys.stderr,
        )
        return 1

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

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(report), encoding="utf-8")
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
