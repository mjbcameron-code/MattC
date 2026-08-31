"""Tip -> ledger -> settlement -> figures, the loop the whole thing exists to run."""

from datetime import datetime, timedelta

import pytest

from vb.config import load_settings
from vb.report import dashboard
from vb.sample import generate_all
from vb.tips.select import build_tipsheet
from vb.track import metrics
from vb.track.ledger import all_bets, legs_for, record_tipsheet
from vb.track.settle import settle_bets


@pytest.fixture
def loaded(conn):
    """Two divisions, with the season paused mid-week so fixtures lie ahead."""
    generate_all(conn, season="2025/26", leagues=["E2", "E3"], seed=11)
    return conn


def test_a_card_is_produced_and_reads_like_english(loaded):
    sheet = build_tipsheet(loaded, days=7, season="2025/26", include_outrights=False)
    assert sheet.all_tips, "the engine found nothing to bet on synthetic soft prices"
    assert sheet.bet_of_the_week is not None
    assert sheet.bet_of_the_week.headline.startswith("Bet of the Week:")
    for tip in sheet.all_tips:
        assert tip.stake_pts > 0
        assert tip.price > 1.0
        assert len(tip.body) > 60
        assert 1 <= tip.confidence <= 5
        assert tip.body[0].isupper() and tip.body.rstrip().endswith((".", "!"))


def test_stakes_respect_the_configured_caps(loaded):
    sheet = build_tipsheet(loaded, days=7, season="2025/26", include_outrights=False)
    for tip in sheet.singles:
        assert 0.25 <= tip.stake_pts <= 3.0
        assert (tip.stake_pts * 100) % 25 == 0        # quarter-point steps


def test_a_long_price_needs_a_real_disagreement(loaded):
    """A big percentage on a longshot is the cheapest edge there is to fake.

    4% of the stake is 2.7 points of probability at 1.50 and 0.17 of a point at
    23.0 — well inside the model's own error. So every single has to beat the
    price in probability as well as in percentage terms.
    """
    settings = load_settings()
    floor = float(settings.get("selection.min_prob_edge", 0.02))
    ceiling = float(settings.get("selection.max_odds", 12.0))
    sheet = build_tipsheet(loaded, days=7, season="2025/26", include_outrights=False)
    assert sheet.singles
    for tip in sheet.singles:
        assert tip.price <= ceiling, f"{tip.selection} tipped at {tip.price}"
        assert tip.edge / tip.price >= floor - 1e-9, (
            f"{tip.selection} at {tip.price}: a {tip.edge:.1%} edge is only "
            f"{tip.edge / tip.price:.2%} of probability"
        )


def test_no_two_bets_on_the_same_angle(loaded):
    sheet = build_tipsheet(loaded, days=7, season="2025/26", include_outrights=False)
    from vb.tips.select import MARKET_FAMILY
    seen = set()
    for tip in sheet.singles:
        key = (tip.match_id, MARKET_FAMILY.get(tip.raw_market, tip.raw_market))
        assert key not in seen, f"two bets on the same angle: {tip.selection}"
        seen.add(key)


def test_the_ledger_records_and_does_not_duplicate(loaded):
    sheet = build_tipsheet(loaded, days=7, season="2025/26", include_outrights=False)
    first = record_tipsheet(loaded, sheet)
    assert sum(first.values()) == len(sheet.all_tips)
    assert record_tipsheet(loaded, sheet) == {}, "re-running must not double the ledger"
    for bet in all_bets(loaded):
        assert legs_for(loaded, bet["id"]), f"{bet['ref']} was stored with no legs"


def test_settlement_closes_the_loop(loaded):
    """Tip the past, settle it, and check the arithmetic of the points column."""
    as_of = datetime.now() - timedelta(weeks=12)
    sheet = build_tipsheet(loaded, days=7, as_of=as_of, season="2025/26",
                           include_outrights=False, statuses=("played",))
    record_tipsheet(loaded, sheet)
    settle_bets(loaded)

    settled = [b for b in all_bets(loaded) if b["status"] != "pending"]
    assert settled, "nothing settled even though the results are all in"
    for bet in settled:
        stake, returned = float(bet["stake_pts"]), float(bet["returned_pts"])
        assert float(bet["pnl_pts"]) == pytest.approx(returned - stake)
        if bet["status"] == "won" and bet["bet_type"] != "acca":
            assert returned == pytest.approx(stake * float(bet["price"]))
        if bet["status"] == "lost":
            assert returned == 0.0

    summary = metrics.summarise(loaded)
    assert summary.settled == len(settled)
    assert summary.pnl == pytest.approx(sum(float(b["pnl_pts"]) for b in settled))
    assert summary.staked == pytest.approx(sum(float(b["stake_pts"]) for b in settled))


def test_the_dashboard_renders(loaded):
    sheet = build_tipsheet(loaded, days=7, season="2025/26", include_outrights=False)
    record_tipsheet(loaded, sheet)
    html = dashboard.render(dashboard.build_context(loaded, sheet, synthetic=True))
    assert "<title>" in html and "Demonstration data" in html
    assert "GambleAware" in html
    # every theme token must be defined on bare :root, not only inside a media query
    root_block = html.split(":root {", 1)[1].split("}", 1)[0]
    for token in ("--paper", "--card", "--ink", "--profit", "--loss", "--hero-bg"):
        assert token in root_block, f"{token} is not defined for the default theme"


def test_doctor_passes_a_healthy_database_and_fails_an_empty_one(loaded, tmp_path,
                                                                 capsys):
    """The health check has to be trustworthy in both directions."""
    from types import SimpleNamespace

    from vb.cli import cmd_doctor

    empty = SimpleNamespace(db=str(tmp_path / "empty.db"))
    assert cmd_doctor(empty) == 1
    assert "No matches loaded" in capsys.readouterr().out

    healthy = SimpleNamespace(db=None)
    import vb.config as config
    original = config.DB_PATH
    try:
        config.DB_PATH = tmp_path / "healthy.db"
        # Reuse the populated fixture's data by pointing the check at it.
        import shutil
        import sqlite3
        source = loaded.execute("PRAGMA database_list").fetchone()["file"]
        loaded.commit()
        shutil.copy(source, config.DB_PATH)
        healthy = SimpleNamespace(db=str(config.DB_PATH))
        assert cmd_doctor(healthy) == 0
        out = capsys.readouterr().out
        assert "no duplicates detected" in out
        assert "Everything the tipping needs is in place" in out
    finally:
        config.DB_PATH = original


def test_a_promoted_club_is_not_mistaken_for_a_misspelling(conn, capsys):
    """One match played can mean a bad name match — or a club just promoted."""
    from types import SimpleNamespace

    from vb.cli import cmd_doctor
    from vb.repo import upsert_match

    for i in range(20):
        upsert_match(conn, "I1", "2025/26", f"2026-01-{(i % 27) + 1:02d}T15:00:00",
                     "Juventus", f"Opponent {i}", fthg=1, ftag=1)
    upsert_match(conn, "I1", "2026/27", "2026-08-24T15:00:00",
                 "Frosinone", "Juventus", fthg=0, ftag=2)
    conn.commit()

    path = conn.execute("PRAGMA database_list").fetchone()["file"]
    cmd_doctor(SimpleNamespace(db=path))
    out = capsys.readouterr().out
    assert "newly promoted" in out
    assert "spelling mismatch" not in out, "a promoted club is not a fault"


def test_a_real_misspelling_is_still_caught(conn, capsys):
    from types import SimpleNamespace

    from vb.cli import cmd_doctor
    from vb.repo import resolve_team, upsert_match

    for i in range(20):
        upsert_match(conn, "I1", "2025/26", f"2026-01-{(i % 27) + 1:02d}T15:00:00",
                     "Hellas Verona", f"Opponent {i}", fthg=1, ftag=1)
    # A spelling the matcher rejected, now sitting alone with one match.
    conn.execute("INSERT INTO teams (name, league_code) VALUES ('Verona FC', 'I1')")
    stray = conn.execute("SELECT id FROM teams WHERE name = 'Verona FC'").fetchone()["id"]
    home = resolve_team(conn, "Juventus", "I1")
    conn.execute(
        "INSERT INTO matches (league_code, season, kickoff, match_date, home_id, "
        "away_id, status, fthg, ftag) VALUES "
        "('I1','2026/27','2026-08-24T15:00:00','2026-08-24',?,?,'played',1,1)",
        (home, stray))
    conn.commit()

    cmd_doctor(SimpleNamespace(db=conn.execute("PRAGMA database_list").fetchone()["file"]))
    out = capsys.readouterr().out
    assert "probably the same club as Hellas Verona" in out
    assert "spelling mismatch" in out


def test_the_weekly_cycle_runs_end_to_end(loaded, tmp_path, monkeypatch, capsys):
    """One command has to survive every step, including a dead data source."""
    import argparse

    from vb.cli import cmd_weekly

    monkeypatch.setenv("VB_REPORT_DIR", str(tmp_path))
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    loaded.commit()
    path = loaded.execute("PRAGMA database_list").fetchone()["file"]

    status = cmd_weekly(argparse.Namespace(
        db=path, days=7, history=1, out=str(tmp_path / "dash.html"),
        dry_run=True, no_odds=True, no_open=True))
    assert status == 0
    out = capsys.readouterr().out
    assert "THE CARD" in out
    assert (tmp_path / "dash.html").exists()


def test_one_dead_host_is_reported_once_not_per_league(capsys, tmp_path,
                                                       monkeypatch):
    """A wall of identical tracebacks buries the single fact that matters."""
    import argparse

    from vb.cli import cmd_update
    from vb.sources import footballdata, http

    def refuse(*args, **kwargs):
        raise http.FetchError("could not reach www.football-data.co.uk "
                              "(blocked by a proxy on this network)")

    monkeypatch.setattr(footballdata, "load_season", refuse)
    monkeypatch.setattr(footballdata, "load_fixtures", refuse)
    cmd_update(argparse.Namespace(
        db=str(tmp_path / "x.db"), leagues="E0,E1,E2,E3", season=None, history=1,
        odds=False, no_odds=True, scores=False, no_fixtures=False,
        fixtures_only=False, no_xg=True, force=False))
    out = capsys.readouterr().out
    assert out.count("blocked by a proxy") == 1, "the same cause, reported once"
    assert "affects E0" in out


def test_the_same_bet_is_never_recorded_twice(loaded):
    """References carry the tip's rank, so ranking is not identity.

    The moment a price moves the ordering shifts, and an identical bet arrives
    under a new reference. Deduplicating on the reference let it onto the
    ledger again, double-counting its stake and its result.
    """
    from vb.tips.select import build_tipsheet
    from vb.track.ledger import find_duplicates, record_tipsheet

    sheet = build_tipsheet(loaded, days=7, season="2026/27", include_outrights=False)
    first = sum(record_tipsheet(loaded, sheet).values())
    assert first, "no tips to test with"

    for offset, tip in enumerate(sheet.singles, start=len(sheet.singles) + 1):
        tip.ref = f"{sheet.week_ref}-{offset:02d}"
    assert sum(record_tipsheet(loaded, sheet).values()) == 0
    assert find_duplicates(loaded) == []
    assert loaded.execute(
        "SELECT COUNT(*) FROM bets").fetchone()[0] == first


def test_a_settled_bet_can_never_be_pruned(loaded):
    """A record you can delete losers from is not a record."""
    from vb.tips.select import build_tipsheet
    from vb.track.ledger import drop_open_bets, record_tipsheet

    record_tipsheet(loaded, build_tipsheet(loaded, days=7, season="2026/27",
                                           include_outrights=False))
    ref = loaded.execute("SELECT ref FROM bets LIMIT 1").fetchone()["ref"]
    loaded.execute("UPDATE bets SET status = 'lost', pnl_pts = -1.0 WHERE ref = ?",
                   (ref,))
    drop_open_bets(loaded)
    survivor = loaded.execute("SELECT status FROM bets WHERE ref = ?", (ref,)).fetchone()
    assert survivor is not None and survivor["status"] == "lost"
    assert loaded.execute(
        "SELECT COUNT(*) FROM bets WHERE status = 'pending'").fetchone()[0] == 0


def test_the_sample_generator_is_actually_reproducible():
    """`hash()` on a string is salted per process, so it cannot seed anything.

    This caught a real flake: the same seed gave a different card in every run,
    so a test that needed two bets sometimes found one.
    """
    import subprocess
    import sys

    script = (
        "import sys; sys.path.insert(0, '.');"
        "from vb.sample import _seed; print(_seed('E2', '2026/27', 3))"
    )
    seeds = {
        subprocess.run([sys.executable, "-c", script], capture_output=True,
                       text=True, check=True, env={"PYTHONHASHSEED": str(salt)},
                       cwd=str(__import__("pathlib").Path(__file__).parent.parent)
                       ).stdout.strip()
        for salt in (0, 1, 2)
    }
    assert len(seeds) == 1, f"the seed moves with PYTHONHASHSEED: {seeds}"


def test_explain_shows_the_workings_for_one_fixture(loaded, tmp_path, capsys):
    """The engine's strongest views get binned unexamined; this is the look."""
    import shutil
    from types import SimpleNamespace

    from vb.cli import cmd_explain

    loaded.commit()
    source = loaded.execute("PRAGMA database_list").fetchone()["file"]
    db = tmp_path / "explain.db"
    shutil.copy(source, db)

    team = loaded.execute(
        "SELECT t.name FROM teams t JOIN matches m ON m.home_id = t.id "
        "WHERE m.status = 'scheduled' LIMIT 1").fetchone()["name"]

    assert cmd_explain(SimpleNamespace(db=str(db), team=team, market="h2h")) == 0
    out = capsys.readouterr().out
    assert team in out
    assert "of the say against the market" in out
    # the three columns that let you judge a disagreement
    for column in ("model", "market", "blend", "edge"):
        assert column in out
    assert "every price on file" in out


def test_explain_is_honest_when_it_has_nothing(loaded, tmp_path, capsys):
    import shutil
    from types import SimpleNamespace

    from vb.cli import cmd_explain

    loaded.commit()
    source = loaded.execute("PRAGMA database_list").fetchone()["file"]
    db = tmp_path / "explain.db"
    shutil.copy(source, db)

    assert cmd_explain(SimpleNamespace(db=str(db), team="Nonexistent Rovers",
                                       market=None)) == 1
    assert "No upcoming fixture found" in capsys.readouterr().out


def test_explain_ignores_a_fixture_that_has_already_kicked_off(loaded, tmp_path,
                                                              capsys):
    """"Scheduled" is not "upcoming".

    A match whose result never arrived keeps that status indefinitely and,
    being the earliest, sorts to the front — so the command answered about
    last week's game while the one being asked about was still to come.
    """
    import shutil
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    from vb.cli import cmd_explain

    row = loaded.execute(
        "SELECT m.id, t.name FROM matches m JOIN teams t ON t.id = m.home_id "
        "WHERE m.status = 'scheduled' ORDER BY m.kickoff LIMIT 1").fetchone()
    stale = (datetime.now() - timedelta(days=3)).isoformat(timespec="seconds")
    loaded.execute("UPDATE matches SET kickoff = ? WHERE id = ?",
                   (stale, row["id"]))
    loaded.commit()

    source = loaded.execute("PRAGMA database_list").fetchone()["file"]
    db = tmp_path / "stale.db"
    shutil.copy(source, db)

    args = SimpleNamespace(db=str(db), team=row["name"], market="h2h")
    cmd_explain(args)
    out = capsys.readouterr().out
    assert stale[:10] not in out, "answered about a match already played"


def test_explain_says_when_a_result_never_arrived(loaded, tmp_path, capsys):
    import shutil
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    from vb.cli import cmd_explain

    name = loaded.execute(
        "SELECT t.name FROM matches m JOIN teams t ON t.id = m.home_id "
        "WHERE m.status = 'scheduled' LIMIT 1").fetchone()["name"]
    past = (datetime.now() - timedelta(days=3)).isoformat(timespec="seconds")
    loaded.execute(
        "UPDATE matches SET kickoff = ? WHERE status = 'scheduled' "
        "AND (home_id IN (SELECT id FROM teams WHERE name = ?) "
        "  OR away_id IN (SELECT id FROM teams WHERE name = ?))",
        (past, name, name))
    loaded.commit()

    source = loaded.execute("PRAGMA database_list").fetchone()["file"]
    db = tmp_path / "gone.db"
    shutil.copy(source, db)

    assert cmd_explain(SimpleNamespace(db=str(db), team=name, market=None)) == 1
    out = capsys.readouterr().out
    assert "already kicked off" in out and "vb update" in out
