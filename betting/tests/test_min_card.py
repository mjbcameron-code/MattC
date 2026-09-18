"""Never hand back a blank page — without calling the filler value."""

import pytest

from vb.config import load_settings
from vb.sample import generate_all
from vb.tips.select import build_tipsheet


@pytest.fixture
def carded(conn):
    """A card with a minimum of three, on soft synthetic prices."""
    settings = load_settings()
    block = settings.raw["selection"]
    before = block.get("min_card")
    block["min_card"] = 3
    generate_all(conn, season="2026/27", leagues=["E2"], seed=21)
    yield conn
    if before is None:
        block.pop("min_card", None)
    else:
        block["min_card"] = before


def test_the_card_is_never_shorter_than_the_minimum(carded):
    sheet = build_tipsheet(carded, days=7, season="2026/27",
                           include_outrights=False)
    assert len(sheet.singles) >= 3


def test_a_filler_says_on_its_face_that_it_is_not_value(carded):
    """The whole bargain. A card that is never empty is only honest if the
    reader can tell which entries the engine actually rates."""
    sheet = build_tipsheet(carded, days=7, season="2026/27",
                           include_outrights=False)
    for tip in sheet.singles:
        if tip.below_bar:
            assert tip.body.startswith("Not a value bet.")
            assert tip.stake_pts == 0.25
            assert tip.edge < 0.04
        else:
            assert "Not a value bet" not in tip.body


def test_a_filler_never_reaches_a_multiple(carded):
    """Model error compounds per leg, so the weakest legs are the last ones to
    fold together."""
    sheet = build_tipsheet(carded, days=7, season="2026/27",
                           include_outrights=False)
    below = {t.selection for t in sheet.singles if t.below_bar}
    for multiple in sheet.accumulators + sheet.builders:
        for leg in multiple.legs:
            assert leg["selection"] not in below, (
                f"{leg['selection']} did not clear the bar and is in "
                f"{multiple.ref}")


def test_value_still_leads_the_card(carded):
    """Fillers come after anything the engine actually rates, never before."""
    sheet = build_tipsheet(carded, days=7, season="2026/27",
                           include_outrights=False)
    seen_filler = False
    for tip in sheet.singles:
        if tip.below_bar:
            seen_filler = True
        else:
            assert not seen_filler, "a real bet was ranked below a filler"


def test_turning_it_off_restores_an_empty_card(conn):
    settings = load_settings()
    block = settings.raw["selection"]
    before = block.get("min_card")
    block["min_card"] = 0
    try:
        generate_all(conn, season="2026/27", leagues=["E2"], seed=21)
        sheet = build_tipsheet(conn, days=7, season="2026/27",
                               include_outrights=False)
        assert not any(t.below_bar for t in sheet.singles)
    finally:
        if before is None:
            block.pop("min_card", None)
        else:
            block["min_card"] = before
