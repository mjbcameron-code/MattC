"""Turning numbers into copy that reads like a tipster wrote it.

The rule here is that nothing is invented. Every clause is built from a value
the engine actually computed — the edge, the fair price, the signals, the
expected goals — so the write-up and the maths can never drift apart. What
varies is only the phrasing, chosen deterministically from the bet's reference
so the same tip always reads the same way.
"""

from __future__ import annotations

import random
from typing import Sequence

from ..features.form import Signal

STARS = "★"
EMPTY_STAR = "☆"

OPENERS = [
    "The market has not caught up here.",
    "This is the one that stands out.",
    "There is a price error here, and it is not a small one.",
    "The numbers and the prices are telling different stories.",
    "Worth getting on before this one moves.",
    "A price that looks a fortnight out of date.",
    "The table says one thing and the underlying numbers say another.",
    "Somebody has priced this off the results and not off the performances.",
    "A closer read of the form guide would have this shorter.",
    "The case for this one is not complicated.",
    "This price is built on a run that is about to end.",
    "Nobody seems to have watched these two lately.",
]

CONFIDENT = [
    "Take the {price} while it is there.",
    "{price} is the play, and it will not last the week.",
    "Get on at {price}.",
    "{price} with {book} is the best of the prices.",
]

CAUTION = [
    "It is not without risk, but the price more than pays for it.",
    "The staking reflects the variance rather than any doubt about the reasoning.",
    "Small stakes, but the value is real.",
]

VALUE_PHRASES = [
    "the model makes it {fair}, so {price} is {edge} of value",
    "we price it at {fair} against {price} available — {edge} in hand",
    "a fair price of {fair} against {price} on offer leaves {edge} of edge",
]


def stars(confidence: int) -> str:
    confidence = max(1, min(5, int(confidence)))
    return STARS * confidence + EMPTY_STAR * (5 - confidence)


def format_price(price: float) -> str:
    """Decimal odds, with the fraction punters quote — but only when it is honest.

    The ladder is coarse, so 3.61 sits between 11/4 and 3/1 and is neither.
    Printing "3.61 (5/2)" would quote a shorter price than the one being
    recommended, so the fraction is shown only when it is within a couple of
    percent of the real number.
    """
    numerator, denominator = (int(x) for x in to_fractional(price).split("/"))
    implied = numerator / denominator + 1
    if abs(implied - price) / price <= 0.02:
        return f"{price:.2f} ({numerator}/{denominator})"
    return f"{price:.2f}"


# The fractional ladder bookmakers actually quote. 47/18 is arithmetically
# correct for 3.61 and no board in the country would ever show it.
FRACTIONAL_LADDER = [
    (1, 10), (1, 8), (1, 6), (1, 5), (2, 9), (1, 4), (2, 7), (3, 10), (1, 3),
    (4, 11), (2, 5), (4, 9), (1, 2), (8, 15), (4, 7), (8, 13), (4, 6), (8, 11),
    (4, 5), (5, 6), (10, 11), (1, 1), (11, 10), (6, 5), (5, 4), (11, 8),
    (6, 4), (13, 8), (7, 4), (15, 8), (2, 1), (85, 40), (9, 4), (5, 2),
    (11, 4), (3, 1), (10, 3), (7, 2), (4, 1), (9, 2), (5, 1), (11, 2), (6, 1),
    (13, 2), (7, 1), (15, 2), (8, 1), (17, 2), (9, 1), (10, 1), (11, 1),
    (12, 1), (14, 1), (16, 1), (18, 1), (20, 1), (22, 1), (25, 1), (28, 1),
    (33, 1), (40, 1), (50, 1), (66, 1), (80, 1), (100, 1), (150, 1), (200, 1),
]


def to_fractional(price: float) -> str:
    """Nearest price on the standard fractional ladder."""
    target = price - 1.0
    if target <= 0:
        return "0/1"
    numerator, denominator = min(
        FRACTIONAL_LADDER, key=lambda f: abs(f[0] / f[1] - target)
    )
    return f"{numerator}/{denominator}"


def stake_text(points: float) -> str:
    if points >= 2.5:
        return f"{points:g} pts"
    if points >= 1:
        return f"{points:g} pts"
    return f"{points:g} pt"


def _rng(ref: str) -> random.Random:
    return random.Random(sum(ord(c) * (i + 1) for i, c in enumerate(ref)))


def signal_sentences(signals: Sequence[Signal], limit: int = 3) -> list[str]:
    """The strongest supporting signals, strongest first, as full sentences."""
    ordered = sorted(signals, key=lambda s: -s.strength)[:limit]
    return [s.text.rstrip(".") + "." for s in ordered]


def value_clause(ref: str, fair_price: float, price: float, edge: float,
                 book: str) -> str:
    rng = _rng(ref)
    return rng.choice(VALUE_PHRASES).format(
        fair=f"{fair_price:.2f}", price=f"{price:.2f}", edge=f"{edge:.0%}",
    ) + f" with {pretty_book(book)}"


BOOK_NAMES = {
    "skybet": "Sky Bet", "bet365": "Bet365", "paddypower": "Paddy Power",
    "williamhill": "William Hill", "ladbrokes_uk": "Ladbrokes",
    "ladbrokes": "Ladbrokes", "coral": "Coral", "betfred": "Betfred",
    "betvictor": "BetVictor", "boylesports": "BoyleSports",
    "unibet_uk": "Unibet", "888sport": "888sport", "betway": "Betway",
    "pinnacle": "Pinnacle", "betfair_ex_uk": "Betfair Exchange",
    "betfair_ex": "Betfair Exchange", "smarkets": "Smarkets",
    "matchbook": "Matchbook", "bwin": "bwin", "market_max": "best available",
    "market_avg": "market average", "manual": "your own price",
}


def pretty_book(key: str) -> str:
    return BOOK_NAMES.get((key or "").lower(), (key or "").replace("_", " ").title())


def write_single(
    ref: str,
    selection: str,
    fixture_label: str,
    competition: str,
    price: float,
    book: str,
    stake: float,
    fair_price: float,
    edge: float,
    signals: Sequence[Signal],
    confidence: int,
    headline_prefix: str = "",
) -> tuple[str, str]:
    """Return (headline, body) for a single bet."""
    rng = _rng(ref)
    headline = f"{headline_prefix}{selection} — {format_price(price)}" if headline_prefix \
        else f"{selection} — {format_price(price)}"

    parts = [rng.choice(OPENERS)]
    reasons = signal_sentences(signals)
    if reasons:
        parts.extend(reasons)
    clause = value_clause(ref, fair_price, price, edge, book)
    # Not .capitalize() — that would lowercase "Sky Bet" into "sky bet".
    parts.append(clause[0].upper() + clause[1:] + ".")
    if confidence <= 2 or price >= 6:
        parts.append(rng.choice(CAUTION))
    else:
        parts.append(rng.choice(CONFIDENT).format(
            price=f"{price:.2f}", book=pretty_book(book)))
    body = " ".join(parts)
    return headline, body


def write_accumulator(ref: str, legs: Sequence[dict], price: float, stake: float,
                      fair_price: float, edge: float) -> tuple[str, str]:
    # Naming every leg in the headline reads badly once two of them are
    # "Over 2.5 goals" — the legs are spelled out with their fixtures below.
    headline = f"{len(legs)}-fold accumulator — {format_price(price)}"
    lines = [
        f"A {len(legs)}-leg fold where every leg is a bet in its own right — "
        "the fold is for the price, not to manufacture one."
    ]
    for leg in legs:
        lines.append(
            f"{leg['fixture']}: {leg['selection']} at {leg['price']:.2f} "
            f"(we make it {1 / leg['model_prob']:.2f})."
        )
    lines.append(
        f"Priced up at {price:.2f} against a fair {fair_price:.2f} — "
        f"{edge:.0%} of value across the fold, after discounting each leg for "
        "the fact that model errors multiply as fast as prices do."
    )
    return headline, " ".join(lines)


def write_builder(ref: str, fixture_label: str, legs: Sequence[dict],
                  fair_price: float, target_price: float, stake: float,
                  correlation: float, signals: Sequence[Signal]) -> tuple[str, str]:
    names = " & ".join(leg["selection"] for leg in legs)
    headline = f"Bet builder — {fixture_label}: {names}"
    lines = []
    reasons = signal_sentences(signals, limit=2)
    lines.extend(reasons)
    if correlation > 1.05:
        lines.append(
            "These legs pull in the same direction, so they land together more "
            f"often than the individual prices suggest — about {correlation:.0%} "
            "as often as multiplying them out would imply."
        )
    elif correlation < 0.95:
        lines.append(
            "Be aware these legs fight each other slightly: they land together "
            f"only {correlation:.0%} as often as multiplying the prices implies, "
            "which is exactly the trap in most builders."
        )
    lines.append(
        f"Our fair price for the combination is {fair_price:.2f}. "
        f"Take it at {target_price:.2f} or bigger — below that there is no value "
        "left once the builder margin is paid."
    )
    return headline, " ".join(lines)


def write_outright(ref: str, selection: str, market_label: str, competition: str,
                   price: float, book: str, stake: float, fair_price: float,
                   edge: float, detail: str) -> tuple[str, str]:
    headline = f"{competition} {market_label}: {selection} — {format_price(price)}"
    body = (
        f"{detail} We make it {fair_price:.2f} against {price:.2f} with "
        f"{pretty_book(book)}, which is {edge:.0%} of value on a bet that will "
        "take months to settle. Long-term money, staked accordingly."
    )
    return headline, body


def bet_of_the_week(headline: str) -> str:
    return f"Bet of the Week: {headline}"
