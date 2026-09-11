"""The normalized Signal contract (spec sections 4 and 75).

Every strategy returns one of these and nothing else. A Signal carries no
authority to trade: ``execution`` is populated by the RiskEngine, never by the
strategy that produced it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, computed_field, model_validator

from trading_universe.domain.enums import (
    FreshnessStatus,
    MarketRegime,
    OrderSide,
    RejectionReason,
    StrategyKind,
)


class SignalScore(BaseModel):
    """Component scores. Components sum to ``total`` by construction."""

    technical: float = 0.0
    sentiment: float = 0.0
    fundamental: float = 0.0
    political: float | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> float:
        parts = [self.technical, self.sentiment, self.fundamental]
        if self.political is not None:
            parts.append(self.political)
        return round(sum(parts), 2)


class TradeParams(BaseModel):
    """Entry / stop / target geometry (spec section 20)."""

    entry: float
    stop: float
    target: float
    max_position_value: float = 150.0

    @model_validator(mode="after")
    def _validate_long_geometry(self) -> TradeParams:
        # Long-only for V1: stop below entry, target above.
        if self.stop >= self.entry:
            raise ValueError(f"stop {self.stop} must be below entry {self.entry} for a long")
        if self.target <= self.entry:
            raise ValueError(f"target {self.target} must be above entry {self.entry} for a long")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def risk_per_share(self) -> float:
        return round(self.entry - self.stop, 6)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reward_per_share(self) -> float:
        return round(self.target - self.entry, 6)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reward_risk(self) -> float:
        risk = self.entry - self.stop
        if risk <= 0:
            return 0.0
        return round((self.target - self.entry) / risk, 4)

    def minimum_target(self, minimum_reward_risk: float) -> float:
        """entry + (risk_per_share x minimum_reward_risk)."""
        return round(self.entry + (self.entry - self.stop) * minimum_reward_risk, 4)


class SignalFreshness(BaseModel):
    """Per-source freshness at the moment the signal was generated."""

    market_data: FreshnessStatus = FreshnessStatus.UNAVAILABLE
    news: FreshnessStatus = FreshnessStatus.UNAVAILABLE
    fundamentals: FreshnessStatus = FreshnessStatus.UNAVAILABLE
    political: FreshnessStatus | None = None
    details: dict[str, float] = Field(
        default_factory=dict, description="source -> age in seconds"
    )


class MarketContext(BaseModel):
    regime: MarketRegime = MarketRegime.NEUTRAL
    sector_regime: MarketRegime = MarketRegime.NEUTRAL
    strategy_match: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="How well this strategy fits the prevailing regime",
    )


class ExecutionDecision(BaseModel):
    """The RiskEngine's verdict. Strategies must never populate this."""

    allowed: bool = False
    reasons: list[RejectionReason] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    quantity: float | None = None
    position_value: float | None = None

    @property
    def reason(self) -> str | None:
        """First rejection reason, for the compact JSON shape in spec 75."""
        return self.reasons[0].value if self.reasons else None


class Signal(BaseModel):
    """Normalized strategy output."""

    signal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ticker: str
    strategy_id: str
    strategy_kind: StrategyKind = StrategyKind.STANDARD
    sector: str = ""
    subsector: str = ""
    direction: OrderSide = OrderSide.BUY

    generated_at: datetime
    score: SignalScore = Field(default_factory=SignalScore)
    trade: TradeParams
    market: MarketContext = Field(default_factory=MarketContext)
    freshness: SignalFreshness = Field(default_factory=SignalFreshness)
    execution: ExecutionDecision = Field(default_factory=ExecutionDecision)

    # Structured evidence used by the thesis builder and the UI's "why" panel.
    evidence: dict[str, object] = Field(default_factory=dict)
    invalidation: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def confidence(self) -> int:
        """Total score presented as an integer confidence, as the UI shows it."""
        return int(round(self.score.total))

    @property
    def side(self) -> str:
        return "LONG" if self.direction is OrderSide.BUY else "SHORT"
