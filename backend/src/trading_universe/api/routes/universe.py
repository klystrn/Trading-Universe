"""Universe and visualization endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from trading_universe.api.deps import platform_dep
from trading_universe.services.platform import Platform

router = APIRouter(prefix="/api/universe", tags=["universe"])


@router.get("")
def universe_payload(platform: Platform = Depends(platform_dep)) -> dict:
    """Compact per-entity visualization state (spec section 77)."""
    return platform.universe_payload()


@router.get("/sectors")
def sectors(platform: Platform = Depends(platform_dep)) -> list[dict]:
    result = platform.scanner.last_result
    regimes = {s.sector_id: s for s in (result.sector_regimes if result else [])}
    out = []
    for sector_id, sector in sorted(platform.universe.sectors.items()):
        regime = regimes.get(sector_id)
        out.append(
            {
                **sector.model_dump(),
                "members": len(platform.universe.by_sector(sector_id)),
                "subsectors": platform.universe.subsectors_of(sector_id),
                "regime": regime.model_dump(mode="json") if regime else None,
            }
        )
    return out


@router.get("/briefing")
def briefing(platform: Platform = Depends(platform_dep)) -> dict:
    """The daily briefing (spec section 63)."""
    return platform.briefing()


@router.get("/stock/{ticker}")
def stock_detail(ticker: str, platform: Platform = Depends(platform_dep)) -> dict:
    ticker = ticker.upper()
    stock = platform.universe.get(ticker)
    if stock is None:
        raise HTTPException(404, f"{ticker} is not in the universe")

    technicals = platform.features.technicals([ticker])
    fundamentals = platform.features.fundamentals([ticker])
    sentiments = platform.features.sentiments([ticker])
    politicals = platform.features.politicals([ticker])
    quote = platform.market_data.get_quote(ticker)

    result = platform.scanner.last_result
    signals = [s for s in (result.signals if result else []) if s.ticker == ticker]
    position = next(
        (p for p in platform.broker.get_positions() if p.ticker == ticker), None
    )

    return {
        "stock": stock.model_dump(),
        "quote": quote.model_dump(mode="json") if quote else None,
        "technical": (
            technicals[ticker].model_dump(mode="json") if ticker in technicals else None
        ),
        "fundamental": (
            fundamentals[ticker].model_dump(mode="json") if ticker in fundamentals else None
        ),
        "sentiment": (
            sentiments[ticker].model_dump(mode="json") if ticker in sentiments else None
        ),
        "political": (
            politicals[ticker].model_dump(mode="json") if ticker in politicals else None
        ),
        "signals": [s.model_dump(mode="json") for s in signals],
        "position": position.model_dump(mode="json") if position else None,
        "tier": platform.market_data.tier_of(ticker),
        "news": [a.model_dump(mode="json") for a in platform.ingest.news_for(ticker)[:12]],
        "filings": [f.model_dump(mode="json") for f in platform.ingest.filings_for(ticker)[:8]],
    }


@router.get("/candles/{ticker}")
def candles(
    ticker: str, interval: str = "1d", limit: int = 260,
    platform: Platform = Depends(platform_dep),
) -> dict:
    """OHLCV for the charts tab (spec section 38)."""
    ticker = ticker.upper()
    if platform.universe.get(ticker) is None:
        raise HTTPException(404, f"{ticker} is not in the universe")

    bars = platform.market_data.get_candles(ticker, interval=interval, limit=limit)
    technicals = platform.features.technicals([ticker])
    snapshot = technicals.get(ticker)

    result = platform.scanner.last_result
    markers = [
        {
            "time": int(s.generated_at.timestamp()),
            "entry": s.trade.entry,
            "stop": s.trade.stop,
            "target": s.trade.target,
            "strategy": s.strategy_id,
            "score": s.confidence,
            "executable": s.execution.allowed,
        }
        for s in (result.signals if result else [])
        if s.ticker == ticker
    ]

    return {
        "ticker": ticker,
        "interval": interval,
        "candles": [
            {
                "time": int(c.timestamp.timestamp()),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in bars
        ],
        "overlays": _overlays(snapshot),
        "markers": markers,
    }


def _overlays(snapshot) -> dict:
    if snapshot is None:
        return {}
    return {
        "ema20": snapshot.ema20,
        "dma50": snapshot.dma50,
        "dma200": snapshot.dma200,
        "vwap": snapshot.vwap,
        "bb_upper": snapshot.bb_upper,
        "bb_lower": snapshot.bb_lower,
        "atr14": snapshot.atr14,
        "rsi14": snapshot.rsi14,
        "high_20": snapshot.high_20,
        "low_20": snapshot.low_20,
        "swing_low": snapshot.swing_low,
        "swing_high": snapshot.swing_high,
    }
