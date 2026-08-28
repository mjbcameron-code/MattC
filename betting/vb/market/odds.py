"""Reading the market: stripping the overround, and shopping for the best price.

A bookmaker's prices do not add up to 100%. The extra is the margin, and how
you remove it matters: the naive method (divide everything by the total) takes
the same slice off a 1.20 shot and a 25/1 outsider, when in reality the margin
is loaded onto the longshots — the favourite-longshot bias. Shin's method
models that explicitly, which is why it is the default here.

The devigged prices are not just diagnostics. The market is the single best
forecaster in football, so its opinion is blended with the model's before any
bet is sized (see vb/market/value.py).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..config import load_settings


def implied(price: float) -> float:
    return 1.0 / price if price and price > 0 else 0.0


def overround(prices: list[float]) -> float:
    """How much over 100% a set of prices adds up to. 0.05 = a 5% book."""
    return sum(implied(p) for p in prices) - 1.0


# ---------------------------------------------------------------------------
# devigging
# ---------------------------------------------------------------------------
def devig_proportional(prices: list[float]) -> list[float]:
    quoted = [implied(p) for p in prices]
    total = sum(quoted)
    return [q / total for q in quoted] if total > 0 else quoted


def devig_odds_ratio(prices: list[float], tolerance: float = 1e-10) -> list[float]:
    """Keep the odds ratio between quoted and fair constant across selections."""
    quoted = [implied(p) for p in prices]
    total = sum(quoted)
    if total <= 1.0 or len(quoted) < 2:
        return devig_proportional(prices)

    def fair(c: float) -> list[float]:
        return [q / (c * (1 - q) + q) for q in quoted]

    low, high = 1.0, 100.0
    for _ in range(200):
        mid = (low + high) / 2
        if sum(fair(mid)) > 1.0:
            low = mid
        else:
            high = mid
        if high - low < tolerance:
            break
    return fair((low + high) / 2)


def devig_shin(prices: list[float], tolerance: float = 1e-12) -> list[float]:
    """Shin's method: back out the share of insider money, then remove it.

    Takes more margin off the outsiders than the favourite, which is how
    bookmakers actually build a book.
    """
    quoted = [implied(p) for p in prices]
    total = sum(quoted)
    if total <= 1.0 or len(quoted) < 2:
        return devig_proportional(prices)

    def fair(z: float) -> list[float]:
        if z <= 1e-12:
            return [q / total for q in quoted]
        return [
            (((z ** 2 + 4 * (1 - z) * q ** 2 / total) ** 0.5) - z) / (2 * (1 - z))
            for q in quoted
        ]

    low, high = 0.0, 0.9
    for _ in range(200):
        mid = (low + high) / 2
        if sum(fair(mid)) > 1.0:
            low = mid
        else:
            high = mid
        if high - low < tolerance:
            break
    result = fair((low + high) / 2)
    scale = sum(result)
    return [p / scale for p in result] if scale > 0 else result


DEVIG_METHODS = {
    "proportional": devig_proportional,
    "odds_ratio": devig_odds_ratio,
    "shin": devig_shin,
}


def devig(prices: list[float], method: str | None = None) -> list[float]:
    method = method or load_settings().get("devig.method", "shin")
    return DEVIG_METHODS.get(method, devig_shin)(prices)


# ---------------------------------------------------------------------------
# reading prices out of the database
# ---------------------------------------------------------------------------
@dataclass
class Quote:
    bookmaker: str
    market: str
    selection: str
    line: float | None
    price: float
    taken_at: str

    @property
    def implied(self) -> float:
        return implied(self.price)


def latest_quotes(conn: sqlite3.Connection, match_id: int, market: str,
                  line: float | None = None,
                  exclude_closing: bool = True,
                  as_of: str | None = None) -> list[Quote]:
    """The most recent price from each bookmaker for each selection.

    ``as_of`` caps how late a price may have been taken. Backtests must pass it:
    reading a price that was only available after the decision was made is the
    single easiest way to produce a backtest that looks brilliant and is worth
    nothing.
    """
    cutoff = "AND taken_at <= :as_of " if as_of else ""
    sql = (
        "SELECT bookmaker, market, selection, line, price, taken_at FROM odds o "
        "WHERE match_id = :match_id AND market = :market "
        + ("AND is_closing = 0 " if exclude_closing else "")
        + ("AND line IS :line " if line is None else "AND ABS(line - :line) < 1e-9 ")
        + cutoff
        + "AND taken_at = (SELECT MAX(taken_at) FROM odds x WHERE x.match_id = o.match_id "
          "AND x.bookmaker = o.bookmaker AND x.market = o.market "
          "AND x.selection = o.selection AND (x.line IS o.line OR x.line = o.line) "
        + ("AND x.taken_at <= :as_of " if as_of else "")
        + ")"
    )
    rows = conn.execute(sql, {"match_id": match_id, "market": market,
                              "line": line, "as_of": as_of}).fetchall()
    return [Quote(**dict(r)) for r in rows]


def selections_for(quotes: list[Quote]) -> list[str]:
    seen: list[str] = []
    for q in quotes:
        if q.selection not in seen:
            seen.append(q.selection)
    return seen


def best_prices(quotes: list[Quote], allowed_books: list[str] | None = None
                ) -> dict[str, Quote]:
    """Top price available for each selection — the whole point of line shopping."""
    best: dict[str, Quote] = {}
    for q in quotes:
        if allowed_books and q.bookmaker not in allowed_books:
            continue
        current = best.get(q.selection)
        if current is None or q.price > current.price:
            best[q.selection] = q
    return best


def consensus_fair(
    quotes: list[Quote],
    method: str | None = None,
    prefer_books: list[str] | None = None,
) -> dict[str, float]:
    """The market's own view of the true probabilities, margin removed.

    Each bookmaker's complete book is devigged on its own — mixing best prices
    from different books and then devigging would remove a margin that nobody
    actually charged — and the results are averaged.
    """
    by_book: dict[str, list[Quote]] = {}
    for q in quotes:
        by_book.setdefault(q.bookmaker, []).append(q)

    selections = selections_for(quotes)
    if not selections:
        return {}

    totals: dict[str, float] = {s: 0.0 for s in selections}
    weights = 0.0
    for book, book_quotes in by_book.items():
        priced = {q.selection: q.price for q in book_quotes}
        if set(priced) != set(selections) or len(priced) < 2:
            continue                     # an incomplete book cannot be devigged
        ordered = [priced[s] for s in selections]
        fair = devig(ordered, method)
        # Exchanges and sharp books carry more information than the rest.
        weight = 2.5 if prefer_books and book in prefer_books else 1.0
        for s, p in zip(selections, fair):
            totals[s] += p * weight
        weights += weight
    if weights == 0:
        return {}
    return {s: v / weights for s, v in totals.items()}


def market_summary(conn: sqlite3.Connection, match_id: int, market: str,
                   line: float | None = None) -> dict:
    settings = load_settings()
    sharp = list(settings.get("bookmakers.exchanges", []) or []) + ["pinnacle"]
    quotes = latest_quotes(conn, match_id, market, line)
    if not quotes:
        return {}
    allowed = list(settings.get("bookmakers.preferred", []) or [])
    return {
        "quotes": quotes,
        "best": best_prices(quotes, allowed or None),
        "fair": consensus_fair(quotes, prefer_books=sharp),
        "books": sorted({q.bookmaker for q in quotes}),
    }
