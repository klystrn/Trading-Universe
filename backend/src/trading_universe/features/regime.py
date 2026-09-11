"""Market regime classification (spec section 7).

Rule-based and explainable by design. Every regime call carries the checks that
produced it so the Parameters tab can render a "why" list a person can verify.
Statistical learning is deferred until paper-trading history exists (spec 71).
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime

from trading_universe.domain.enums import MarketRegime
from trading_universe.domain.regime import RegimeInputs, RegimeSnapshot
from trading_universe.domain.snapshots import SentimentSnapshot, TechnicalSnapshot


def compute_breadth(snaps: list[TechnicalSnapshot]) -> tuple[float, float, float]:
    """Fractions above 20DMA (approximated by EMA20), 50DMA and 200DMA."""
    if not snaps:
        return 0.0, 0.0, 0.0
    n = len(snaps)
    above_20 = sum(1 for s in snaps if s.ema20 is not None and s.close > s.ema20) / n
    above_50 = sum(1 for s in snaps if s.price_above_50dma) / n
    above_200 = sum(1 for s in snaps if s.price_above_200dma) / n
    return round(above_20, 4), round(above_50, 4), round(above_200, 4)


def momentum_persistence(snaps: list[TechnicalSnapshot]) -> float:
    """Share of names whose RSI is both above 50 and rising - a cheap, readable
    proxy for cross-sectional momentum persistence."""
    usable = [s for s in snaps if s.rsi14 is not None and s.rsi14_prev is not None]
    if not usable:
        return 0.0
    rising = sum(1 for s in usable if s.rsi14 > 50 and s.rsi14 > s.rsi14_prev)
    return round(rising / len(usable), 4)


def realized_volatility(index_snaps: list[TechnicalSnapshot]) -> float:
    """ATR as a fraction of price, averaged - a VIX stand-in when no VIX feed
    is configured."""
    ratios = [s.atr14 / s.close for s in index_snaps if s.atr14 and s.close > 0]
    return round(statistics.fmean(ratios), 6) if ratios else 0.0


def classify(inputs: RegimeInputs) -> tuple[MarketRegime, float, list[str]]:
    """Map regime inputs onto a regime, a confidence and the checks that fired.

    The order matters: risk-off and high-volatility are evaluated before the
    bullish branches so a violent rally inside a broken tape is never mistaken
    for a strong bull market.
    """
    b20 = inputs.breadth_above_20dma or 0.0
    b50 = inputs.breadth_above_50dma or 0.0
    b200 = inputs.breadth_above_200dma or 0.0
    vol = inputs.realized_vol_20d or 0.0
    vix = inputs.vix
    dd = inputs.spy_drawdown_from_52w_high or 0.0
    mom = inputs.momentum_persistence or 0.0
    sentiment = inputs.news_sentiment or 0.0
    above_200 = inputs.spy_above_200dma
    above_50 = inputs.spy_above_50dma

    reasons: list[str] = []
    high_vol = (vix is not None and vix >= 28.0) or vol >= 0.028
    very_high_vol = (vix is not None and vix >= 35.0) or vol >= 0.040

    # --- RISK-OFF ----------------------------------------------------------
    if (b200 < 0.30 and above_200 is False) or (very_high_vol and b50 < 0.30):
        reasons.append(f"only {b200:.0%} of the market above its 200DMA")
        if above_200 is False:
            reasons.append("SPY below its 200DMA")
        if very_high_vol:
            reasons.append("volatility at crisis levels")
        return MarketRegime.RISK_OFF, 0.80, reasons

    # --- CORRECTION --------------------------------------------------------
    if dd <= -0.10 and b50 < 0.40:
        reasons.append(f"index {dd:.0%} off its 52-week high")
        reasons.append(f"only {b50:.0%} of names above their 50DMA")
        return MarketRegime.CORRECTION, 0.75, reasons

    # --- HIGH VOLATILITY ---------------------------------------------------
    if high_vol and b50 < 0.60:
        reasons.append("volatility elevated")
        if vix is not None:
            reasons.append(f"VIX {vix:.1f}")
        reasons.append(f"breadth mixed at {b50:.0%} above 50DMA")
        return MarketRegime.HIGH_VOLATILITY, 0.70, reasons

    # --- RECOVERY ----------------------------------------------------------
    # Repairing from damage: long-term breadth still poor, short-term improving.
    if b200 < 0.50 and b20 >= 0.55 and mom >= 0.40:
        reasons.append(f"short-term breadth recovering ({b20:.0%} above 20DMA)")
        reasons.append(f"long-term breadth still repairing ({b200:.0%} above 200DMA)")
        reasons.append("momentum turning up")
        return MarketRegime.RECOVERY, 0.65, reasons

    # --- STRONG BULL -------------------------------------------------------
    if b50 >= 0.65 and b200 >= 0.70 and mom >= 0.55 and not high_vol:
        reasons.append(f"{b50:.0%} of names above their 50DMA")
        reasons.append(f"{b200:.0%} above their 200DMA")
        reasons.append(f"momentum persistence strong ({mom:.0%})")
        if sentiment > 0.05:
            reasons.append("news sentiment positive")
        if above_50:
            reasons.append("SPY above its 50DMA")
        return MarketRegime.STRONG_BULL, 0.85, reasons

    # --- BULL --------------------------------------------------------------
    if b50 >= 0.50 and b200 >= 0.55:
        reasons.append(f"{b50:.0%} of names above their 50DMA")
        reasons.append(f"{b200:.0%} above their 200DMA")
        reasons.append(f"momentum persistence {mom:.0%}")
        if sentiment >= 0.0:
            reasons.append("news sentiment neutral-to-positive")
        return MarketRegime.BULL, 0.72, reasons

    # --- NEUTRAL -----------------------------------------------------------
    reasons.append(f"breadth mixed ({b50:.0%} above 50DMA, {b200:.0%} above 200DMA)")
    reasons.append("no decisive trend or volatility signal")
    return MarketRegime.NEUTRAL, 0.55, reasons


def build_regime_snapshot(
    all_snaps: list[TechnicalSnapshot],
    index_snaps: list[TechnicalSnapshot] | None = None,
    sentiments: dict[str, SentimentSnapshot] | None = None,
    sector_dispersion: float | None = None,
    vix: float | None = None,
    now: datetime | None = None,
) -> RegimeSnapshot:
    now = now or datetime.now(UTC)
    index_snaps = index_snaps or all_snaps
    sentiments = sentiments or {}

    b20, b50, b200 = compute_breadth(all_snaps)
    mom = momentum_persistence(all_snaps)
    vol = realized_volatility(index_snaps)

    mean_sentiment = (
        round(statistics.fmean([s.score_7d for s in sentiments.values()]), 4)
        if sentiments
        else 0.0
    )

    # Index proxy: mega-cap names stand in for SPY/QQQ when no index feed exists.
    proxy = sorted(index_snaps, key=lambda s: s.avg_dollar_volume_20, reverse=True)[:50]
    above_50 = (
        sum(1 for s in proxy if s.price_above_50dma) / len(proxy) > 0.5 if proxy else None
    )
    above_200 = (
        sum(1 for s in proxy if s.price_above_200dma) / len(proxy) > 0.5 if proxy else None
    )
    above_20 = (
        sum(1 for s in proxy if s.ema20 and s.close > s.ema20) / len(proxy) > 0.5
        if proxy
        else None
    )

    drawdowns = [
        (s.close - s.high_52w) / s.high_52w for s in proxy if s.high_52w and s.high_52w > 0
    ]
    drawdown = round(statistics.fmean(drawdowns), 5) if drawdowns else 0.0

    volumes = [s.volume_ratio for s in all_snaps if s.volume_ratio > 0]
    volume_ratio = round(statistics.fmean(volumes), 4) if volumes else 1.0

    inputs = RegimeInputs(
        spy_above_20dma=above_20,
        spy_above_50dma=above_50,
        spy_above_200dma=above_200,
        qqq_above_50dma=above_50,
        spy_drawdown_from_52w_high=drawdown,
        breadth_above_20dma=b20,
        breadth_above_50dma=b50,
        breadth_above_200dma=b200,
        vix=vix,
        realized_vol_20d=vol,
        news_sentiment=mean_sentiment,
        sector_dispersion=sector_dispersion,
        momentum_persistence=mom,
        market_volume_ratio=volume_ratio,
    )

    regime, confidence, rationale = classify(inputs)
    return RegimeSnapshot(
        as_of=now, regime=regime, confidence=confidence, inputs=inputs, rationale=rationale
    )
