"""Congressional disclosure objects (spec 14-16, 31)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, computed_field

from trading_universe.domain.enums import Chamber, PoliticalOwner, TransactionType


class PoliticalTransaction(BaseModel):
    """One disclosed transaction.

    The distinction between ``transaction_date``, ``disclosure_date`` and
    ``detected_at`` is load-bearing: only the last two are information the system
    could legitimately have acted on (spec section 31).
    """

    transaction_id: str
    politician: str
    chamber: Chamber
    party: str | None = None
    state: str | None = None
    owner: PoliticalOwner = PoliticalOwner.UNKNOWN

    ticker: str
    asset_description: str | None = None
    transaction_type: TransactionType

    amount_low: float = 0.0
    amount_high: float = 0.0

    transaction_date: date
    disclosure_date: date
    detected_at: datetime
    source_url: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def disclosure_lag_days(self) -> int:
        return max(0, (self.disclosure_date - self.transaction_date).days)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def amount_midpoint(self) -> float:
        if self.amount_high > 0:
            return (self.amount_low + self.amount_high) / 2.0
        return self.amount_low

    @property
    def is_purchase(self) -> bool:
        return self.transaction_type is TransactionType.PURCHASE

    @property
    def identity_key(self) -> str:
        """Member and spouse are tracked separately where possible (spec 14)."""
        return f"{self.politician}|{self.owner.value}"


class PoliticianStats(BaseModel):
    """Rolling performance measured strictly from the disclosure date forward."""

    politician: str
    chamber: Chamber
    disclosed_purchases: int = 0
    disclosed_sales: int = 0
    tickers: list[str] = Field(default_factory=list)
    avg_return_30d_post_disclosure: float | None = None
    avg_excess_return_30d: float | None = None
    follow_through_rate: float | None = Field(
        default=None, description="Share of purchases positive 30d after disclosure"
    )
    sample_size: int = 0
