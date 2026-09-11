"""Freshness and data-source health objects (spec 29, 30, 32, 42)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from trading_universe.domain.enums import FreshnessStatus


class FreshnessState(BaseModel):
    """One source's age measured against its configured thresholds."""

    source: str
    status: FreshnessStatus
    age_seconds: float | None = None
    warn_age_seconds: float | None = None
    max_age_seconds: float | None = None
    blocking: bool = False
    last_event_time: datetime | None = None
    last_received_time: datetime | None = None
    detail: str | None = None

    @property
    def is_tradable(self) -> bool:
        """A blocking source that has gone stale forbids dependent execution."""
        if not self.blocking:
            return True
        return self.status in (FreshnessStatus.LIVE, FreshnessStatus.HEALTHY,
                               FreshnessStatus.DEGRADED)


class DataSourceHealth(BaseModel):
    """What the Data Health panel renders (spec section 32)."""

    name: str
    status: FreshnessStatus = FreshnessStatus.UNAVAILABLE
    connected: bool = False
    latency_ms: float | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    quota_used: int | None = None
    quota_limit: int | None = None
    queue_depth: int | None = None
    detail: str | None = None


class SystemHealth(BaseModel):
    as_of: datetime
    overall: FreshnessStatus = FreshnessStatus.UNAVAILABLE
    sources: list[DataSourceHealth] = Field(default_factory=list)
    freshness: list[FreshnessState] = Field(default_factory=list)

    # Execution-side health (spec section 42).
    kill_switch_engaged: bool = False
    auto_trade_enabled: bool = False
    operating_mode: str = "ADVISORY"
    trading_env: str = "PAPER"
    allow_real_orders: bool = False
    database_healthy: bool = True
    scanner_running: bool = False
    open_orders: int = 0
    rejected_orders_today: int = 0
    last_scan_at: datetime | None = None
    last_sync_at: datetime | None = None
    session: str = "CLOSED"

    # Which strategies may currently execute, and why not where applicable.
    strategy_gates: dict[str, str] = Field(default_factory=dict)

    @property
    def degraded(self) -> bool:
        return self.overall not in (FreshnessStatus.LIVE, FreshnessStatus.HEALTHY)
