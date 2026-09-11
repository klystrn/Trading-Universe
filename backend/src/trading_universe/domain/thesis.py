"""Machine-readable trade thesis (spec section 21).

Persisted for every signal - accepted AND rejected - so later analysis can ask
whether rejected 65-score setups outperformed accepted 70-score setups.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from trading_universe.domain.enums import RejectionReason


class TradeThesis(BaseModel):
    trade_id: str
    signal_id: str
    ticker: str
    strategy: str
    side: str = "LONG"

    signal_score: float
    technical_score: float
    sentiment_score: float
    fundamental_score: float
    political_score: float | None = None

    entry: float
    stop: float
    target: float
    reward_risk: float
    max_position_value: float

    technical: dict[str, object] = Field(default_factory=dict)
    sentiment: dict[str, object] = Field(default_factory=dict)
    fundamentals: dict[str, object] = Field(default_factory=dict)
    political: dict[str, object] | None = None
    market: dict[str, object] = Field(default_factory=dict)
    freshness: dict[str, object] = Field(default_factory=dict)

    invalidation: str
    generated_at: datetime

    # Rejected theses are first-class records, not discarded work.
    accepted: bool = False
    rejection_reasons: list[RejectionReason] = Field(default_factory=list)
