"""Watchlist (spec sections 37, 69).

Watchlisted names get scan PRIORITY and prominent placement. They never get a
score bonus - biasing the score because the user is watching would corrupt the
signal (spec 69).
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from trading_universe.api.deps import platform_dep
from trading_universe.services.platform import Platform

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("")
def get_watchlist(platform: Platform = Depends(platform_dep)) -> dict:
    rows = platform.repository.watchlist()
    prices = platform.market_data.prices()
    result = platform.scanner.last_result
    best: dict[str, object] = {}
    for signal in result.signals if result else []:
        if signal.ticker not in best:
            best[signal.ticker] = {
                "score": signal.confidence,
                "strategy": signal.strategy_id,
                "executable": signal.execution.allowed,
            }

    politicals = platform.features.politicals([r["ticker"] for r in rows])
    for row in rows:
        ticker = row["ticker"]
        stock = platform.universe.get(ticker)
        row["name"] = stock.name if stock else ticker
        row["sector"] = stock.sector if stock else "unknown"
        row["price"] = prices.get(ticker)
        row["signal"] = best.get(ticker)
        row["tier"] = platform.market_data.tier_of(ticker)
        political = politicals.get(ticker)
        row["political_activity"] = (
            political.purchases_30d if political else 0
        )

    return {
        "count": len(rows),
        "watchlist": rows,
        "note": "Watchlist entries receive scan priority, never a score bonus.",
    }


@router.post("")
def add(
    ticker: str = Body(..., embed=True),
    note: str | None = Body(default=None, embed=True),
    pinned: bool = Body(default=False, embed=True),
    alert_above: float | None = Body(default=None, embed=True),
    alert_below: float | None = Body(default=None, embed=True),
    platform: Platform = Depends(platform_dep),
) -> dict:
    ticker = ticker.upper()
    if platform.universe.get(ticker) is None:
        raise HTTPException(404, f"{ticker} is not in the universe")
    platform.repository.add_watchlist(ticker, note, pinned, alert_above, alert_below)
    tickers = platform.repository.watchlist_tickers()
    # Promote immediately so the name starts receiving real-time quotes.
    platform.market_data.set_watchlist(tickers)
    platform.market_data.promote(
        sorted(platform.market_data.focus), sorted(platform.market_data.candidates)
    )
    return {"watchlist": tickers}


@router.delete("/{ticker}")
def remove(ticker: str, platform: Platform = Depends(platform_dep)) -> dict:
    platform.repository.remove_watchlist(ticker)
    tickers = platform.repository.watchlist_tickers()
    platform.market_data.set_watchlist(tickers)
    return {"watchlist": tickers}
