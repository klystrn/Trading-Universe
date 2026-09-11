"""Shared fixtures. Tests run against the deterministic demo market, so every
assertion is reproducible."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

os.environ.setdefault("TU_DATA_MODE", "DEMO")
os.environ.setdefault("TRADING_ENV", "PAPER")
os.environ.setdefault("ALLOW_REAL_ORDERS", "false")


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Each test gets its own SQLite file."""
    monkeypatch.setenv("TU_DATABASE_URL", f"sqlite:///{tmp_path}/test.sqlite")
    from trading_universe.db.session import reset_engine
    from trading_universe.settings import reload_settings

    reload_settings()
    reset_engine()
    yield
    reset_engine()


@pytest.fixture
def config():
    from trading_universe.config import reload_config

    return reload_config()


@pytest.fixture
def universe():
    from trading_universe.data.universe import get_universe

    return get_universe()


@pytest.fixture
def freshness():
    from trading_universe.data.freshness import FreshnessService

    service = FreshnessService()
    # Mark every source current so tests exercise the check under test rather
    # than tripping over unrelated staleness.
    now = datetime.now(UTC)
    for source in (
        "quote_active_candidate", "quote_open_position", "candle_daily",
        "candle_intraday", "news_discovery", "news_sentiment_aggregate",
        "sec_filing", "fundamental_ratios", "political_disclosure",
        "market_breadth", "sector_regime",
    ):
        service.record(source, event_time=now, received_time=now)
    return service


@pytest.fixture
def demo_provider():
    from trading_universe.data.demo import DemoMarketDataProvider

    provider = DemoMarketDataProvider()
    provider.connect()
    return provider


@pytest.fixture
def paper_broker():
    from trading_universe.execution.paper import PaperBroker

    broker = PaperBroker(starting_cash=10_000.0, slippage_bps=0.0)
    broker.connect()
    return broker


@pytest.fixture
def sample_signal():
    """A clean, executable long signal: entry 100, stop 96, target 107 (1.75R)."""
    from trading_universe.domain.enums import FreshnessStatus, StrategyKind
    from trading_universe.domain.signals import (
        Signal,
        SignalFreshness,
        SignalScore,
        TradeParams,
    )

    return Signal(
        ticker="AAPL",
        strategy_id="quality_momentum_pullback",
        strategy_kind=StrategyKind.STANDARD,
        sector="information_technology",
        subsector="Technology Hardware",
        generated_at=datetime.now(UTC),
        score=SignalScore(technical=32.0, sentiment=24.0, fundamental=25.0),
        trade=TradeParams(entry=100.0, stop=96.0, target=107.0, max_position_value=150.0),
        freshness=SignalFreshness(
            market_data=FreshnessStatus.LIVE,
            news=FreshnessStatus.HEALTHY,
            fundamentals=FreshnessStatus.HEALTHY,
        ),
        invalidation="break below 96.00",
    )


@pytest.fixture
def risk_context(paper_broker):
    from trading_universe.domain.enums import OperatingMode, Session
    from trading_universe.execution.risk_engine import RiskContext

    return RiskContext(
        portfolio=paper_broker.get_portfolio(),
        session=Session.REGULAR,
        now=datetime.now(UTC),
        operating_mode=OperatingMode.PAPER_AUTO,
        active_strategy=None,
    )


@pytest.fixture
def liquid_technical():
    """A technical snapshot that comfortably clears every liquidity gate."""
    from trading_universe.domain.snapshots import TechnicalSnapshot

    return TechnicalSnapshot(
        ticker="AAPL",
        as_of=datetime.now(UTC),
        close=100.0,
        avg_volume_20=5_000_000.0,
        avg_dollar_volume_20=500_000_000.0,
        volume_ratio=1.3,
        bars_available=260,
    )


@pytest.fixture
def tight_quote():
    from trading_universe.domain.enums import Session
    from trading_universe.domain.market import Quote

    now = datetime.now(UTC)
    return Quote(
        ticker="AAPL", last=100.0, bid=99.99, ask=100.01, volume=1_000_000,
        prev_close=99.0, session=Session.REGULAR, event_time=now, received_time=now,
    )


@pytest.fixture
def yesterday():
    return datetime.now(UTC) - timedelta(days=1)
