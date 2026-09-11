"""Data health and system status (spec sections 32, 42)."""

from __future__ import annotations

from datetime import UTC, datetime

from trading_universe.config import get_config
from trading_universe.data.freshness import FreshnessService
from trading_universe.domain.enums import DataMode, FreshnessStatus
from trading_universe.domain.health import DataSourceHealth, SystemHealth
from trading_universe.settings import get_settings


class HealthService:
    def __init__(self, platform: Platform) -> None:  # noqa: F821
        self.platform = platform

    @property
    def freshness(self) -> FreshnessService:
        return self.platform.freshness

    def snapshot(self) -> SystemHealth:
        now = datetime.now(UTC)
        settings = get_settings()
        risk = get_config().risk
        sources = self._sources(now)
        freshness_states = self.freshness.all_states(now)

        last_scan = self.platform.scanner.last_result
        health = SystemHealth(
            as_of=now,
            overall=self.freshness.overall_status(now),
            sources=sources,
            freshness=freshness_states,
            kill_switch_engaged=risk.kill_switch_engaged,
            auto_trade_enabled=self.platform.execution.auto_trade_armed,
            operating_mode=self.platform.execution.operating_mode.value,
            trading_env=settings.trading_env,
            allow_real_orders=settings.allow_real_orders,
            read_only=settings.read_only,
            database_healthy=self._database_healthy(),
            scanner_running=self.platform.scheduler_running,
            open_orders=len(self.platform.broker.get_open_orders()),
            rejected_orders_today=self.platform.execution.rejected_today,
            last_scan_at=last_scan.finished_at if last_scan else None,
            last_sync_at=self.platform.last_sync_at,
            session=self.platform.market_data.session(),
            strategy_gates=self.strategy_gates(now),
        )
        return health

    def strategy_gates(self, now: datetime | None = None) -> dict[str, str]:
        """Which strategies may currently execute, and why not where applicable.

        This is what lets Momentum Pullback stay tradable while Catalyst Breakout
        reports "DISABLED - NEWS FEED DEGRADED" (spec section 30).
        """
        now = now or datetime.now(UTC)
        cfg = get_config().strategies
        out: dict[str, str] = {}
        for sid in cfg.all_strategy_ids():
            if not cfg.strategy(sid).get("enabled", True):
                out[sid] = "DISABLED - turned off in configuration"
                continue
            ok, blockers, _ = self.freshness.evaluate_strategy(sid, now)
            if ok:
                out[sid] = "MAY TRADE"
            else:
                pretty = ", ".join(b.replace("_", " ").upper() for b in blockers)
                out[sid] = f"DISABLED - {pretty} UNAVAILABLE OR STALE"
        return out

    def _sources(self, now: datetime) -> list[DataSourceHealth]:
        settings = get_settings()
        demo = settings.data_mode is DataMode.DEMO
        out: list[DataSourceHealth] = []

        quote_state = self.freshness.state("quote_active_candidate", now)
        out.append(
            DataSourceHealth(
                name="MOOMOO" if not demo else "DEMO FEED",
                status=quote_state.status,
                connected=self.platform.market_data.connected,
                latency_ms=(
                    round(
                        (self.freshness.latency("quote_active_candidate", now)["source_latency"]
                         or 0.0) * 1000.0,
                        1,
                    )
                ),
                last_success_at=quote_state.last_received_time,
                detail=quote_state.detail,
            )
        )

        sec_state = self.freshness.state("sec_filing", now)
        out.append(
            DataSourceHealth(
                name="SEC",
                status=sec_state.status,
                connected=sec_state.status is not FreshnessStatus.UNAVAILABLE,
                last_success_at=sec_state.last_received_time,
                detail=sec_state.detail,
            )
        )

        news_state = self.freshness.state("news_discovery", now)
        out.append(
            DataSourceHealth(
                name="GDELT",
                status=news_state.status,
                connected=news_state.status is not FreshnessStatus.UNAVAILABLE,
                last_success_at=news_state.last_received_time,
                detail=news_state.detail,
            )
        )

        marketaux = self.platform.ingest._marketaux
        out.append(
            DataSourceHealth(
                name="MARKETAUX",
                status=(
                    FreshnessStatus.HEALTHY
                    if (marketaux and marketaux.configured)
                    else FreshnessStatus.UNAVAILABLE
                ),
                connected=bool(marketaux and marketaux.configured),
                quota_used=marketaux.quota_used if marketaux else None,
                quota_limit=marketaux.daily_limit if marketaux else None,
                detail=None if (marketaux and marketaux.configured) else "no API key configured",
            )
        )

        political_state = self.freshness.state("political_disclosure", now)
        out.append(
            DataSourceHealth(
                name="CONGRESS",
                status=political_state.status,
                connected=political_state.status is not FreshnessStatus.UNAVAILABLE,
                last_success_at=political_state.last_received_time,
                detail=political_state.detail,
            )
        )

        engine = self.platform.sentiment_engine_name
        loaded = getattr(self.platform.sentiment_engine, "loaded", True)
        out.append(
            DataSourceHealth(
                name="FINBERT" if engine == "finbert" else "SENTIMENT (LEXICON)",
                status=FreshnessStatus.HEALTHY if loaded else FreshnessStatus.DEGRADED,
                connected=True,
                queue_depth=0,
                detail=(
                    "model loaded" if engine == "finbert" and loaded
                    else "FinBERT not loaded; using the lexicon engine"
                    if engine == "finbert"
                    else "financial lexicon engine"
                ),
            )
        )
        return out

    def _database_healthy(self) -> bool:
        try:
            from sqlalchemy import text

            from trading_universe.db.session import session_scope

            with session_scope() as session:
                session.execute(text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001
            return False
