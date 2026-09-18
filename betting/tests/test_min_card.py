"""Never hand back a blank page — without calling the filler value."""

import pytest

from vb.config import load_settings
from vb.sample import generate_all
from vb.tips.select import build_tipsheet


@pytest.fixture
def carded(conn):
    """A card with a minimum of three, under a calibration correction.

    The correction is the point. Without one the synthetic prices are soft
    enough that genuine value fills the card on its own and the filler path is
    never exercised — which is how three of these tests passed without checking
    anything. A real database has a correction in force, and that is exactly
    when a card needs topping up.
    """
    settings = load_settings()
    block = settings.raw["selection"]
    model = settings.raw["model"]
    before = block.get("min_card"), model.get("calibration")
    block["min_card"] = 3
    model["calibration"] = {"slope": 1.0, "intercept": -0.253}
    generate_all(conn, season="2026/27", leagues=["E2", "E3"], seed=33)
    yield conn
    block["min_card"], model["calibration"] = (
        before[0] if before[0] is not None else 3,
        before[1] if before[1] is not None else {"slope": 1.0, "intercept": 0.0})


def test_the_fixture_actually_produces_fillers(carded):
    """Guard the guard: if this stops producing fillers the rest go vacuous."""
    sheet = build_tipsheet(carded, days=7, season="2026/27",
                           include_outrights=False)
    assert any(t.below_bar for t in sheet.singles), (
        "no filler produced, so every test below this one is checking nothing")


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


def test_a_filler_never_argues_that_it_is_value(carded):
    """The write-up has to agree with its own first sentence.

    Prefixing "not a value bet" onto prose that then says the price "more than
    pays for it" produces a tip that contradicts itself in three sentences,
    which is worse than either half on its own. With a negative edge the same
    clause reads "leaves -1.3% of edge", which is not English.
    """
    sheet = build_tipsheet(carded, days=7, season="2026/27",
                           include_outrights=False)
    fillers = [t for t in sheet.singles if t.below_bar]
    assert fillers, "no filler produced to check"
    for tip in fillers:
        assert "of edge" not in tip.body
        assert "more than pays for it" not in tip.body
        assert "what it needs to be worth backing" in tip.body


def test_a_filler_states_both_prices(carded):
    sheet = build_tipsheet(carded, days=7, season="2026/27",
                           include_outrights=False)
    for tip in sheet.singles:
        if tip.below_bar:
            assert f"{tip.price:.2f}" in tip.body, "the price on offer"
            assert "We make it" in tip.body, "and what we make it"


def test_a_negative_edge_reads_as_under_not_as_a_minus_sign(carded):
    from vb.tips.language import write_single

    _, body = write_single(
        ref="T1", selection="Reading", fixture_label="Reading v Hull",
        competition="EFL Championship", price=2.50, book="bet365", stake=0.25,
        fair_price=2.60, edge=-0.038, signals=[], confidence=1, below_bar=True)
    assert "3.8% under what it needs to be" in body
    assert "-3.8%" not in body


def test_a_level_price_says_so(carded):
    from vb.tips.language import write_single

    _, body = write_single(
        ref="T2", selection="Reading", fixture_label="Reading v Hull",
        competition="EFL Championship", price=2.50, book="bet365", stake=0.25,
        fair_price=2.50, edge=0.001, signals=[], confidence=1, below_bar=True)
    assert "level with what it needs to be" in body
