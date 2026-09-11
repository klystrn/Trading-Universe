"""SQLAlchemy models."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class SignalRow(Base):
    """Every signal generated, executable or not.

    Rejected signals are stored deliberately (spec section 21): without them
    there is no way to ask whether the threshold is set correctly.
    """

    __tablename__ = "signals"

    signal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    strategy_id: Mapped[str] = mapped_column(String(64), index=True)
    strategy_kind: Mapped[str] = mapped_column(String(16))
    sector: Mapped[str] = mapped_column(String(64), default="")
    subsector: Mapped[str] = mapped_column(String(96), default="")
    direction: Mapped[str] = mapped_column(String(8), default="BUY")

    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    trading_day: Mapped[date] = mapped_column(Date, index=True)

    score_total: Mapped[float] = mapped_column(Float, index=True)
    score_technical: Mapped[float] = mapped_column(Float, default=0.0)
    score_sentiment: Mapped[float] = mapped_column(Float, default=0.0)
    score_fundamental: Mapped[float] = mapped_column(Float, default=0.0)
    score_political: Mapped[float | None] = mapped_column(Float, nullable=True)

    entry: Mapped[float] = mapped_column(Float)
    stop: Mapped[float] = mapped_column(Float)
    target: Mapped[float] = mapped_column(Float)
    reward_risk: Mapped[float] = mapped_column(Float)

    market_regime: Mapped[str] = mapped_column(String(32), default="NEUTRAL")
    sector_regime: Mapped[str] = mapped_column(String(32), default="NEUTRAL")
    strategy_match: Mapped[float] = mapped_column(Float, default=0.0)

    allowed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    rejection_reasons: Mapped[list] = mapped_column(JSON, default=list)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    freshness: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    invalidation: Mapped[str] = mapped_column(Text, default="")

    # Forward returns, backfilled by analytics so accepted and rejected signals
    # can be compared on equal terms.
    forward_return_5d: Mapped[float | None] = mapped_column(Float, nullable=True)
    forward_return_20d: Mapped[float | None] = mapped_column(Float, nullable=True)
    mfe_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae_r: Mapped[float | None] = mapped_column(Float, nullable=True)


Index("ix_signals_day_strategy", SignalRow.trading_day, SignalRow.strategy_id)


class ThesisRow(Base):
    __tablename__ = "theses"

    trade_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(64), index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    strategy: Mapped[str] = mapped_column(String(64), index=True)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class OrderRow(Base):
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[float] = mapped_column(Float)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    filled_quantity: Mapped[float] = mapped_column(Float, default=0.0)
    avg_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    strategy_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operating_mode: Mapped[str] = mapped_column(String(16), default="ADVISORY")
    execution_source: Mapped[str] = mapped_column(String(24), default="AUTO")
    paper: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class TradeRow(Base):
    """What the Trade Log renders (spec section 36)."""

    __tablename__ = "trades"

    trade_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    strategy_id: Mapped[str] = mapped_column(String(64), index=True)
    sector: Mapped[str] = mapped_column(String(64), default="", index=True)

    entry: Mapped[float] = mapped_column(Float)
    stop: Mapped[float] = mapped_column(Float)
    target: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    operating_mode: Mapped[str] = mapped_column(String(16), default="ADVISORY")
    execution_source: Mapped[str] = mapped_column(String(24), default="AUTO", index=True)
    paper: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    was_recommended_strategy: Mapped[bool] = mapped_column(Boolean, default=True)

    signal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    thesis_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    result: Mapped[str] = mapped_column(String(16), default="OPEN", index=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    r_multiple: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_regime: Mapped[str | None] = mapped_column(String(32), nullable=True)


class DailyRecommendationRow(Base):
    """Stored each day so later analysis can measure whether the regime selector
    actually improved performance (spec section 6)."""

    __tablename__ = "daily_recommendations"

    trading_day: Mapped[date] = mapped_column(Date, primary_key=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    primary_strategy: Mapped[str] = mapped_column(String(64), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    market_regime: Mapped[str] = mapped_column(String(32), index=True)
    rationale: Mapped[list] = mapped_column(JSON, default=list)
    sector_recommendations: Mapped[list] = mapped_column(JSON, default=list)
    alternatives: Mapped[list] = mapped_column(JSON, default=list)
    accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    active_strategy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    overridden: Mapped[bool] = mapped_column(Boolean, default=False)


class PoliticalTransactionRow(Base):
    __tablename__ = "political_transactions"

    transaction_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    politician: Mapped[str] = mapped_column(String(128), index=True)
    chamber: Mapped[str] = mapped_column(String(16), index=True)
    party: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    state: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    owner: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    asset_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    transaction_type: Mapped[str] = mapped_column(String(16), index=True)
    amount_low: Mapped[float] = mapped_column(Float, default=0.0)
    amount_high: Mapped[float] = mapped_column(Float, default=0.0)
    transaction_date: Mapped[date] = mapped_column(Date, index=True)
    disclosure_date: Mapped[date] = mapped_column(Date, index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class WatchlistRow(Base):
    """Watchlist entries get scan PRIORITY but never a score bonus (spec 69)."""

    __tablename__ = "watchlist"

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    alert_above: Mapped[float | None] = mapped_column(Float, nullable=True)
    alert_below: Mapped[float | None] = mapped_column(Float, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ScanRunRow(Base):
    """One scan cycle, for the System tab's 'last successful scan'."""

    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tickers_scanned: Mapped[int] = mapped_column(Integer, default=0)
    signals_found: Mapped[int] = mapped_column(Integer, default=0)
    executable: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    market_regime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
