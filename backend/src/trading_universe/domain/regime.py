"""Market and sector regime objects plus the daily strategy recommendation."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from trading_universe.domain.enums import MarketRegime


class RegimeInputs(BaseModel):
    """The explainable inputs behind a regime call (spec section 7).

    These are surfaced verbatim in the Parameters tab's "Why" list, so every
    field here must be something a person can read and check.
    """

    spy_above_20dma: bool | None = None
    spy_above_50dma: bool | None = None
    spy_above_200dma: bool | None = None
    qqq_above_50dma: bool | None = None
    spy_20d_return: float | None = None
    spy_drawdown_from_52w_high: float | None = None

    breadth_above_20dma: float | None = Field(default=None, description="0-1")
    breadth_above_50dma: float | None = None
    breadth_above_200dma: float | None = None

    vix: float | None = None
    realized_vol_20d: float | None = None
    atr_percentile: float | None = None

    news_sentiment: float | None = None
    advance_decline: float | None = None

    sector_dispersion: float | None = None
    momentum_persistence: float | None = None
    market_volume_ratio: float | None = None


class RegimeSnapshot(BaseModel):
    as_of: datetime
    regime: MarketRegime
    confidence: float = Field(ge=0.0, le=1.0)
    inputs: RegimeInputs = Field(default_factory=RegimeInputs)
    rationale: list[str] = Field(
        default_factory=list, description="Human-readable checks that fired"
    )


class SectorRegime(BaseModel):
    sector_id: str
    as_of: datetime
    regime: MarketRegime
    session_performance: float = 0.0
    relative_strength: float = 0.0
    rs_label: str = "NEUTRAL"
    breadth: float = 0.0
    news_sentiment: float = 0.0
    signal_count: int = 0
    political_activity: int = 0
    recommended_strategy: str | None = None
    confidence: float = 0.0
    rationale: list[str] = Field(default_factory=list)


class StrategyRecommendation(BaseModel):
    """Stored daily so future analysis can score the regime selector itself
    (spec section 6)."""

    trading_day: date
    generated_at: datetime
    primary_strategy: str
    confidence: float = Field(ge=0.0, le=1.0)
    market_regime: MarketRegime
    rationale: list[str] = Field(default_factory=list)
    sector_recommendations: list[SectorRegime] = Field(default_factory=list)
    alternatives: list[tuple[str, float]] = Field(default_factory=list)

    # Filled in when the user accepts or overrides.
    accepted: bool | None = None
    active_strategy: str | None = None
    overridden: bool = False
