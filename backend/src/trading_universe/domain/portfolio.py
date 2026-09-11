"""Orders, positions, trades and portfolio state."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, computed_field

from trading_universe.domain.enums import (
    ExecutionSource,
    OperatingMode,
    OrderSide,
    OrderStatus,
    OrderType,
    TradeResult,
)


class Order(BaseModel):
    order_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    broker_order_id: str | None = None
    client_order_id: str = Field(
        default_factory=lambda: f"tu-{uuid.uuid4().hex[:16]}",
        description="Idempotency key sent to the broker",
    )

    ticker: str
    side: OrderSide
    order_type: OrderType = OrderType.LIMIT
    quantity: float
    limit_price: float | None = None
    stop_price: float | None = None

    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    avg_fill_price: float | None = None

    signal_id: str | None = None
    strategy_id: str | None = None
    operating_mode: OperatingMode = OperatingMode.ADVISORY
    execution_source: ExecutionSource = ExecutionSource.AUTO
    paper: bool = True

    created_at: datetime
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
    rejection_reason: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def notional(self) -> float:
        price = self.avg_fill_price or self.limit_price or 0.0
        return round(self.quantity * price, 4)


class Position(BaseModel):
    ticker: str
    quantity: float
    avg_entry: float
    current_price: float = 0.0

    stop: float | None = None
    target: float | None = None
    strategy_id: str | None = None
    signal_id: str | None = None
    trade_id: str | None = None
    opened_at: datetime | None = None
    paper: bool = True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def market_value(self) -> float:
        return round(self.quantity * self.current_price, 4)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cost_basis(self) -> float:
        return round(self.quantity * self.avg_entry, 4)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unrealized_pnl(self) -> float:
        return round((self.current_price - self.avg_entry) * self.quantity, 4)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unrealized_pnl_pct(self) -> float:
        if self.avg_entry <= 0:
            return 0.0
        return round((self.current_price - self.avg_entry) / self.avg_entry, 6)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def r_multiple(self) -> float | None:
        """Unrealized result expressed in initial-risk units."""
        if self.stop is None:
            return None
        risk = self.avg_entry - self.stop
        if risk <= 0:
            return None
        return round((self.current_price - self.avg_entry) / risk, 4)


class Trade(BaseModel):
    """A completed or in-flight round trip. This is what the Trade Log renders."""

    trade_id: str
    ticker: str
    strategy_id: str
    sector: str = ""

    entry: float
    stop: float
    target: float
    quantity: float
    exit_price: float | None = None

    opened_at: datetime
    closed_at: datetime | None = None
    exit_reason: str | None = None

    operating_mode: OperatingMode = OperatingMode.ADVISORY
    execution_source: ExecutionSource = ExecutionSource.AUTO
    paper: bool = True
    was_recommended_strategy: bool = True

    signal_id: str | None = None
    thesis_id: str | None = None
    result: TradeResult = TradeResult.OPEN

    @computed_field  # type: ignore[prop-decorator]
    @property
    def position_value(self) -> float:
        return round(self.entry * self.quantity, 4)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def realized_pnl(self) -> float | None:
        if self.exit_price is None:
            return None
        return round((self.exit_price - self.entry) * self.quantity, 4)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def r_multiple(self) -> float | None:
        if self.exit_price is None:
            return None
        risk = self.entry - self.stop
        if risk <= 0:
            return None
        return round((self.exit_price - self.entry) / risk, 4)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def holding_days(self) -> float | None:
        if self.closed_at is None:
            return None
        return round((self.closed_at - self.opened_at).total_seconds() / 86400.0, 3)


class Portfolio(BaseModel):
    """Spec section 41. Separate from the trade log."""

    as_of: datetime
    cash: float = 0.0
    buying_power: float = 0.0
    positions: list[Position] = Field(default_factory=list)
    realized_pnl_today: float = 0.0
    realized_pnl_total: float = 0.0
    paper: bool = True

    # Capacity, straight from the risk configuration.
    max_open_positions: int = 5
    max_new_trades_per_day: int = 3
    trades_opened_today: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_exposure(self) -> float:
        return round(sum(p.market_value for p in self.positions), 4)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def portfolio_value(self) -> float:
        return round(self.cash + self.total_exposure, 4)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unrealized_pnl(self) -> float:
        return round(sum(p.unrealized_pnl for p in self.positions), 4)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def open_position_count(self) -> int:
        return len(self.positions)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def remaining_position_slots(self) -> int:
        return max(0, self.max_open_positions - len(self.positions))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def remaining_daily_entries(self) -> int:
        return max(0, self.max_new_trades_per_day - self.trades_opened_today)

    def sector_exposure(self, sector_of: dict[str, str]) -> dict[str, float]:
        out: dict[str, float] = {}
        for p in self.positions:
            sector = sector_of.get(p.ticker, "unknown")
            out[sector] = round(out.get(sector, 0.0) + p.market_value, 4)
        return out

    def strategy_exposure(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for p in self.positions:
            key = p.strategy_id or "unknown"
            out[key] = round(out.get(key, 0.0) + p.market_value, 4)
        return out
