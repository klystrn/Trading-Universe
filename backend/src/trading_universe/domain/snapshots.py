"""Feature-engine outputs. Each snapshot is the complete, timestamped input a
strategy is allowed to reason about for one ticker."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from trading_universe.domain.enums import CatalystType


class TechnicalSnapshot(BaseModel):
    ticker: str
    as_of: datetime

    close: float = 0.0
    prev_close: float | None = None
    change_pct: float = 0.0
    ema20: float | None = None
    dma50: float | None = None
    dma200: float | None = None
    rsi14: float | None = None
    rsi14_prev: float | None = None
    atr14: float | None = None
    vwap: float | None = None

    bb_upper: float | None = None
    bb_lower: float | None = None
    bb_width: float | None = None
    bb_width_percentile: float | None = Field(
        default=None, description="Percentile of current BB width within its lookback"
    )
    bb_width_percentile_prev: float | None = Field(
        default=None,
        description="Same, excluding the latest bar - the pre-trigger compression state",
    )

    volume: int = 0
    avg_volume_20: float = 0.0
    volume_ratio: float = 0.0
    avg_dollar_volume_20: float = 0.0

    high_20: float | None = None
    low_20: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    swing_low: float | None = None
    swing_high: float | None = None

    pct_from_20d_high: float | None = None
    atr_contracting: bool = False
    volume_declining: bool = False
    price_above_50dma: bool = False
    price_above_200dma: bool = False
    dma50_above_dma200: bool = False
    ema20_pullback: bool = False
    dma50_pullback: bool = False
    vwap_reclaimed: bool = False
    reclaimed_50dma: bool = False
    recently_below_50dma: bool = False
    broke_20d_high: bool = False
    higher_low: bool = False
    bullish_engulfing: bool = False
    near_lower_band: bool = False
    rsi_recently_oversold: bool = False
    rsi_turning_up: bool = False

    bars_available: int = 0


class FundamentalSnapshot(BaseModel):
    ticker: str
    as_of: datetime
    source_filing_date: datetime | None = None
    source_form: str | None = None

    revenue_yoy: float | None = None
    operating_margin: float | None = None
    operating_margin_change: float | None = None
    free_cash_flow: float | None = None
    free_cash_flow_positive: bool | None = None
    fcf_yield: float | None = None
    net_debt_to_ebitda: float | None = None
    debt_trend: str | None = None
    roe: float | None = None
    roa: float | None = None
    share_count_change: float | None = None
    earnings_consistency: float | None = None
    pe_ratio: float | None = None

    quality_score: float = Field(default=0.0, ge=0.0, le=100.0)
    value_percentile: float | None = Field(
        default=None, description="Cross-sectional value rank within the screened universe"
    )


class SentimentSnapshot(BaseModel):
    ticker: str
    as_of: datetime

    score_24h: float = Field(default=0.0, ge=-1.0, le=1.0)
    score_7d: float = Field(default=0.0, ge=-1.0, le=1.0)
    score_30d: float = Field(default=0.0, ge=-1.0, le=1.0)
    headline_count_24h: int = 0
    headline_count_7d: int = 0
    trend: str = "flat"
    engine: str = "lexicon"

    catalyst_type: CatalystType | None = None
    catalyst_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    catalyst_at: datetime | None = None
    catalyst_sessions_ago: int | None = None

    @property
    def improving(self) -> bool:
        return self.trend == "improving"

    @property
    def deteriorating(self) -> bool:
        return self.trend == "deteriorating"


class PoliticalSnapshot(BaseModel):
    """Aggregated disclosure state for a ticker.

    Every field here is derived from DISCLOSURE dates, never transaction dates,
    so backtests cannot leak look-ahead information (spec section 31).
    """

    ticker: str
    as_of: datetime

    purchases_30d: int = 0
    sales_30d: int = 0
    distinct_politicians_30d: int = 0
    distinct_politicians_180d: int = 0
    chambers_30d: list[str] = Field(default_factory=list)
    newest_disclosure_at: datetime | None = None
    newest_disclosure_age_days: float | None = None
    newest_transaction_lag_days: float | None = None
    total_amount_low_30d: float = 0.0
    total_amount_high_30d: float = 0.0
    largest_band_usd: float = 0.0
    repeat_buyers: dict[str, int] = Field(
        default_factory=dict, description="politician -> purchase count in window"
    )
    politicians_with_sales: list[str] = Field(default_factory=list)

    # Subscores computed by features.political, 0-1.
    consensus_score: float = 0.0
    freshness_score: float = 0.0
    repeat_score: float = 0.0
