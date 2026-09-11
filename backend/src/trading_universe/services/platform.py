"""The application container.

Wires the layers together once and hands the API a single object to talk to.
Provider selection (demo vs Moomoo) happens here and nowhere else.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any

from trading_universe.config import get_config
from trading_universe.data.base import MarketDataProvider
from trading_universe.data.demo import DemoMarketDataProvider
from trading_universe.data.freshness import FreshnessService
from trading_universe.data.universe import get_universe
from trading_universe.db import Repository, init_db
from trading_universe.domain.enums import DataMode, OperatingMode
from trading_universe.execution.broker_base import BrokerBase
from trading_universe.execution.engine import ExecutionEngine
from trading_universe.execution.paper import PaperBroker
from trading_universe.execution.risk_engine import RiskEngine
from trading_universe.features.sentiment import get_sentiment_engine
from trading_universe.services.briefing import build_briefing
from trading_universe.services.health import HealthService
from trading_universe.services.ingest import IngestService
from trading_universe.services.market_data import MarketDataService
from trading_universe.services.scanner import FeatureStore, Scanner, ScanResult
from trading_universe.services.universe_viz import UniverseLayout, build_universe_payload
from trading_universe.settings import get_settings

logger = logging.getLogger(__name__)


class Platform:
    """Everything the API needs, assembled once."""

    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.config = get_config()
        self.universe = get_universe()
        self.freshness = FreshnessService()
        self.repository = Repository()

        init_db()

        self.provider: MarketDataProvider = self._build_provider()
        self.market_data = MarketDataService(self.provider, self.freshness)
        self.features = FeatureStore(self.market_data, self.freshness, self.universe)
        self.ingest = IngestService(
            self.features, self.freshness, self.universe,
            settings.data_mode, self.repository,
        )

        self.broker: BrokerBase = self._build_broker()
        self.risk = RiskEngine(self.config, self.freshness)
        self.execution = ExecutionEngine(self.broker, self.risk, settings.operating_mode)
        self.scanner = Scanner(
            self.market_data, self.freshness, self.execution,
            self.features, self.universe, self.repository,
        )
        self.health = HealthService(self)
        self.layout = UniverseLayout(self.universe)

        self.scheduler = None
        self.scheduler_running = False
        self.last_sync_at: datetime | None = None
        self._lock = threading.RLock()
        self._bootstrapped = False
        # Surfaced by /api/system/status so a cold-started deployment can tell
        # the HUD what it is doing instead of leaving it staring at a spinner.
        self.bootstrap_stage: str = "starting"
        self.bootstrap_error: str | None = None

    # -- construction --------------------------------------------------------
    def _build_provider(self) -> MarketDataProvider:
        if self.settings.data_mode is DataMode.DEMO:
            logger.info("DEMO data mode: using the synthetic market generator")
            return DemoMarketDataProvider()
        try:
            from trading_universe.execution.moomoo import MoomooMarketData

            provider = MoomooMarketData()
            provider.connect()
            logger.info("connected to Moomoo OpenD")
            return provider
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Moomoo unavailable (%s); falling back to the demo feed. "
                "Set TU_DATA_MODE=DEMO to silence this.",
                exc,
            )
            self.freshness.mark_unavailable("quote_active_candidate", str(exc))
            return DemoMarketDataProvider()

    def _build_broker(self) -> BrokerBase:
        settings = self.settings
        if settings.data_mode is DataMode.DEMO or settings.operating_mode is OperatingMode.ADVISORY:
            return PaperBroker(starting_cash=settings.paper_starting_cash)
        try:
            from trading_universe.execution.moomoo import MoomooBroker

            broker = MoomooBroker(paper=not settings.real_orders_permitted)
            broker.connect()
            broker.unlock_trade()
            return broker
        except Exception as exc:  # noqa: BLE001
            logger.error("Moomoo broker unavailable (%s); using the internal paper broker", exc)
            return PaperBroker(starting_cash=settings.paper_starting_cash)

    # -- lifecycle -----------------------------------------------------------
    def bootstrap(self, warm_tickers: int | None = None) -> dict[str, Any]:
        """Connect, load history and run the first ingest + scan."""
        with self._lock:
            try:
                self.bootstrap_stage = "connecting"
                self.market_data.connect()
                self.broker.connect()
                self.market_data.set_watchlist(self.repository.watchlist_tickers())

                tickers = self.universe.tickers()
                if warm_tickers:
                    tickers = tickers[:warm_tickers]

                self.bootstrap_stage = f"loading {len(tickers)} candle series"
                loaded = self.market_data.warm_candles(tickers)
                self.bootstrap_stage = "ingesting filings, news and congressional data"
                counts = self.ingest.ingest_all(tickers)
                self.bootstrap_stage = f"scanning {len(tickers)} tickers"
                result = self.scanner.run(tickers, execute=False)
                self._apply_recommendation_if_unset(result)
                self.last_sync_at = datetime.now(UTC)
                self._bootstrapped = True
                self.bootstrap_stage = "ready"
            except Exception as exc:
                self.bootstrap_error = str(exc)
                self.bootstrap_stage = "failed"
                raise

            return {
                "tickers": len(tickers),
                "candle_series_loaded": loaded,
                **counts,
                "signals": len(result.signals),
                "executable": len(result.executable),
                "regime": result.regime.regime.value if result.regime else None,
            }

    @property
    def bootstrapped(self) -> bool:
        return self._bootstrapped

    def _apply_recommendation_if_unset(self, result: ScanResult) -> None:
        """Adopt the recommendation only when the user has not chosen.

        A manual override must survive the next scan, so this never overwrites an
        explicit choice (spec section 67).
        """
        if self.execution.active_strategy is not None:
            return
        if result.recommendation and result.recommendation.primary_strategy != "NO_TRADE":
            self.execution.set_active_strategy(result.recommendation.primary_strategy)

    def refresh(self, execute: bool = True) -> ScanResult:
        """One full cycle: quotes, ingest, scan, sync."""
        with self._lock:
            tickers = self.universe.tickers()
            focus = sorted(self.market_data.focus | self.market_data.candidates)
            self.market_data.refresh_quotes(focus or tickers[:50])
            self.broker.sync(self.market_data.prices())
            result = self.scanner.run(tickers, execute=execute)
            self._apply_recommendation_if_unset(result)
            self._persist_broker_state()
            self.last_sync_at = datetime.now(UTC)
            return result

    def sync_only(self) -> None:
        """Fast path for the quote loop: refresh prices and mark positions."""
        with self._lock:
            subscribed = sorted(self.market_data.focus | self.market_data.candidates)
            held = [p.ticker for p in self.broker.get_positions()]
            self.market_data.refresh_quotes(sorted(set(subscribed) | set(held)))
            self.broker.sync(self.market_data.prices())
            self._persist_broker_state()
            self.last_sync_at = datetime.now(UTC)

    def _persist_broker_state(self) -> None:
        getter = getattr(self.broker, "get_trades", None)
        if getter is None:
            return
        for trade in getter():
            self.repository.save_trade(trade, sector=self.universe.sector_of(trade.ticker))
        orders = getattr(self.broker, "get_orders", lambda: [])()
        for order in orders:
            self.repository.save_order(order)

    def shutdown(self) -> None:
        with self._lock:
            # SchedulerService owns the scheduler lifecycle and is shut down
            # first by the lifespan handler. AsyncIOScheduler.shutdown() defers
            # to the event loop, so a second call here would race it.
            self.scheduler_running = False
            self.ingest.close()
            self.market_data.disconnect()
            self.broker.disconnect()

    # -- views ----------------------------------------------------------------
    @property
    def sentiment_engine(self):
        return get_sentiment_engine()

    @property
    def sentiment_engine_name(self) -> str:
        return self.settings.sentiment_engine

    def universe_payload(self) -> dict[str, Any]:
        result = self.scanner.last_result
        tickers = self.universe.tickers()
        technicals = (
            result.technicals if result and result.technicals
            else self.features.technicals(tickers)
        )
        return build_universe_payload(
            universe=self.universe,
            layout=self.layout,
            quotes=self.market_data.quotes(),
            technicals=technicals,
            signals=result.signals if result else [],
            positions=self.broker.get_positions(),
            politicals=self.features.politicals(tickers),
            watchlist=self.repository.watchlist_tickers(),
            sector_regimes=result.sector_regimes if result else [],
        )

    def briefing(self) -> dict[str, Any]:
        return build_briefing(
            self.scanner.last_result,
            self.broker.get_portfolio(),
            self.repository.political_summary(),
        )


_platform: Platform | None = None
_platform_lock = threading.Lock()


def get_platform() -> Platform:
    global _platform
    if _platform is None:
        with _platform_lock:
            if _platform is None:
                _platform = Platform()
    return _platform


def reset_platform() -> None:
    global _platform
    with _platform_lock:
        if _platform is not None:
            _platform.shutdown()
        _platform = None
