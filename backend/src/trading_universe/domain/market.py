"""Market structure objects: sectors, stocks, quotes, candles."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, computed_field

from trading_universe.domain.enums import Session


class Subsector(BaseModel):
    id: str
    label: str
    sector_id: str


class Sector(BaseModel):
    id: str
    label: str
    short: str
    hue: int = Field(ge=0, le=360, description="Base hue for universe rendering")


class Stock(BaseModel):
    """A tradable entity in the universe."""

    ticker: str
    name: str
    sector: str
    subsector: str
    indices: list[str] = Field(default_factory=list)
    market_cap_musd: float = 0.0

    # Set by the universe loader for dual-class listings (GOOG/GOOGL).
    # The non-primary class is still tradable but is hidden from the 3D scene so
    # the same company does not occupy two stars (spec 60).
    primary_class: bool = True
    dedup_group: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def market_cap_usd(self) -> float:
        return self.market_cap_musd * 1_000_000.0


class Quote(BaseModel):
    """A point-in-time price observation.

    ``event_time`` is when the underlying market event occurred; ``received_time``
    is when Trading Universe learned about it. Both are mandatory so latency and
    data age are always computable (spec section 28).
    """

    ticker: str
    last: float
    bid: float | None = None
    ask: float | None = None
    volume: int = 0
    prev_close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    session: Session = Session.REGULAR

    event_time: datetime
    received_time: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def mid(self) -> float:
        if self.bid is not None and self.ask is not None and self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return self.last

    @computed_field  # type: ignore[prop-decorator]
    @property
    def spread_pct(self) -> float | None:
        """Quoted spread as a fraction of mid. ``None`` when no book is available."""
        if self.bid is None or self.ask is None or self.bid <= 0 or self.ask <= 0:
            return None
        mid = (self.bid + self.ask) / 2.0
        if mid <= 0:
            return None
        return (self.ask - self.bid) / mid

    @computed_field  # type: ignore[prop-decorator]
    @property
    def change_pct(self) -> float:
        if not self.prev_close:
            return 0.0
        return (self.last - self.prev_close) / self.prev_close

    def age_seconds(self, now: datetime) -> float:
        return max(0.0, (now - self.event_time).total_seconds())


class Candle(BaseModel):
    """OHLCV bar. ``timestamp`` is the bar's opening time."""

    ticker: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    interval: str = "1d"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def typical_price(self) -> float:
        return (self.high + self.low + self.close) / 3.0
