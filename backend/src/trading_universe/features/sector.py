"""Sector aggregation: relative strength, breadth, dispersion (spec 6, 58)."""

from __future__ import annotations

import statistics
from datetime import UTC, datetime

from trading_universe.domain.enums import MarketRegime
from trading_universe.domain.regime import SectorRegime
from trading_universe.domain.snapshots import (
    PoliticalSnapshot,
    SentimentSnapshot,
    TechnicalSnapshot,
)


def _mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 6) if values else 0.0


def sector_breadth(snaps: list[TechnicalSnapshot], attr: str = "price_above_50dma") -> float:
    """Fraction of a sector's names satisfying a trend flag, 0-1."""
    if not snaps:
        return 0.0
    return round(sum(1 for s in snaps if getattr(s, attr)) / len(snaps), 4)


def sector_return(snaps: list[TechnicalSnapshot], lookback_attr: str = "ema20") -> float:
    """Proxy session/short-term return: mean close vs mean EMA20."""
    ratios = [
        (s.close - getattr(s, lookback_attr)) / getattr(s, lookback_attr)
        for s in snaps
        if getattr(s, lookback_attr)
    ]
    return _mean(ratios)


def relative_strength(sector_value: float, market_value: float) -> float:
    """Sector performance minus market performance."""
    return round(sector_value - market_value, 6)


def rs_label(rs: float) -> str:
    if rs >= 0.02:
        return "STRONG"
    if rs >= 0.005:
        return "IMPROVING"
    if rs <= -0.02:
        return "WEAK"
    if rs <= -0.005:
        return "SOFTENING"
    return "NEUTRAL"


def dispersion(values: list[float]) -> float:
    """Cross-sectional standard deviation - how differently sectors behave."""
    if len(values) < 2:
        return 0.0
    return round(statistics.pstdev(values), 6)


def classify_sector_regime(
    breadth_50: float, breadth_200: float, rs: float, mean_rsi: float, vol_percentile: float
) -> MarketRegime:
    """Same rule vocabulary as the market regime, applied within a sector."""
    if vol_percentile >= 0.85 and breadth_50 < 0.45:
        return MarketRegime.HIGH_VOLATILITY
    if breadth_50 >= 0.70 and breadth_200 >= 0.75 and rs > 0.0:
        return MarketRegime.STRONG_BULL
    if breadth_50 >= 0.55 and breadth_200 >= 0.60:
        return MarketRegime.BULL
    if breadth_200 < 0.35 and mean_rsi < 42:
        return MarketRegime.CORRECTION
    if breadth_50 >= 0.45 and breadth_200 < 0.50 and mean_rsi >= 45:
        return MarketRegime.RECOVERY
    if breadth_50 < 0.30:
        return MarketRegime.RISK_OFF
    return MarketRegime.NEUTRAL


def build_sector_regimes(
    technicals_by_sector: dict[str, list[TechnicalSnapshot]],
    sentiment_by_ticker: dict[str, SentimentSnapshot] | None = None,
    political_by_ticker: dict[str, PoliticalSnapshot] | None = None,
    signal_counts: dict[str, int] | None = None,
    now: datetime | None = None,
) -> tuple[list[SectorRegime], float]:
    """Build one :class:`SectorRegime` per sector.

    Returns ``(regimes, dispersion)`` where dispersion is the cross-sectional
    spread of sector returns - a regime input in its own right (spec 7).
    """
    now = now or datetime.now(UTC)
    sentiment_by_ticker = sentiment_by_ticker or {}
    political_by_ticker = political_by_ticker or {}
    signal_counts = signal_counts or {}

    all_snaps = [s for snaps in technicals_by_sector.values() for s in snaps]
    market_return = sector_return(all_snaps)

    sector_returns: dict[str, float] = {}
    out: list[SectorRegime] = []

    for sector_id, snaps in technicals_by_sector.items():
        if not snaps:
            continue
        ret = sector_return(snaps)
        sector_returns[sector_id] = ret
        breadth_50 = sector_breadth(snaps, "price_above_50dma")
        breadth_200 = sector_breadth(snaps, "price_above_200dma")
        rsis = [s.rsi14 for s in snaps if s.rsi14 is not None]
        mean_rsi = _mean(rsis) if rsis else 50.0

        widths = [s.bb_width_percentile for s in snaps if s.bb_width_percentile is not None]
        vol_pct = (_mean(widths) / 100.0) if widths else 0.5

        tickers = [s.ticker for s in snaps]
        sentiments = [
            sentiment_by_ticker[t].score_7d for t in tickers if t in sentiment_by_ticker
        ]
        political = sum(
            1
            for t in tickers
            if t in political_by_ticker and political_by_ticker[t].purchases_30d > 0
        )

        rs = relative_strength(ret, market_return)
        regime = classify_sector_regime(breadth_50, breadth_200, rs, mean_rsi, vol_pct)

        rationale = [
            f"{breadth_50:.0%} of names above their 50DMA",
            f"{breadth_200:.0%} above their 200DMA",
            f"relative strength {rs:+.2%} vs the market",
            f"mean RSI {mean_rsi:.0f}",
        ]
        if political:
            rationale.append(f"{political} name(s) with disclosed political purchases")

        out.append(
            SectorRegime(
                sector_id=sector_id,
                as_of=now,
                regime=regime,
                session_performance=round(ret, 6),
                relative_strength=rs,
                rs_label=rs_label(rs),
                breadth=breadth_50,
                news_sentiment=_mean(sentiments),
                signal_count=signal_counts.get(sector_id, 0),
                political_activity=political,
                rationale=rationale,
            )
        )

    out.sort(key=lambda s: s.relative_strength, reverse=True)
    return out, dispersion(list(sector_returns.values()))
