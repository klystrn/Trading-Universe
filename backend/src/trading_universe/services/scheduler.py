"""APScheduler jobs (spec section 23).

Three cadences, matching the tiering model:

    quote sync   - fast, only the subscribed focus/candidate tiers
    scan         - the full pipeline
    ingest       - fundamentals, news and disclosures (slow-moving)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from trading_universe.config import get_config
from trading_universe.services.platform import Platform
from trading_universe.websocket.hub import WebSocketHub

logger = logging.getLogger(__name__)


class SchedulerService:
    def __init__(self, platform: Platform, hub: WebSocketHub) -> None:
        self.platform = platform
        self.hub = hub
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        tiers = get_config().universe.tiers
        quote_interval = int(tiers.get("candidate", {}).get("scan_interval_seconds", 15))
        scan_interval = int(tiers.get("focus", {}).get("scan_interval_seconds", 60))
        broad_interval = int(tiers.get("broad", {}).get("scan_interval_seconds", 900))

        self._loop = asyncio.get_running_loop()
        self.scheduler.add_job(
            self._quote_job, "interval", seconds=quote_interval,
            id="quotes", max_instances=1, coalesce=True,
        )
        self.scheduler.add_job(
            self._scan_job, "interval", seconds=max(scan_interval, 30),
            id="scan", max_instances=1, coalesce=True,
        )
        self.scheduler.add_job(
            self._ingest_job, "interval", seconds=max(broad_interval, 300),
            id="ingest", max_instances=1, coalesce=True,
        )
        self.scheduler.start()
        self.platform.scheduler = self.scheduler
        self.platform.scheduler_running = True
        logger.info(
            "scheduler started (quotes %ds, scan %ds, ingest %ds)",
            quote_interval, scan_interval, broad_interval,
        )

    def shutdown(self) -> None:
        """Idempotent: AsyncIOScheduler.shutdown() is deferred to the event loop,
        so ``running`` can still read True immediately after a shutdown call."""
        from contextlib import suppress

        from apscheduler.schedulers import SchedulerNotRunningError

        with suppress(SchedulerNotRunningError):
            self.scheduler.shutdown(wait=False)
        self.platform.scheduler_running = False

    # -- jobs ---------------------------------------------------------------
    async def _quote_job(self) -> None:
        try:
            await asyncio.to_thread(self.platform.sync_only)
            await self.hub.broadcast("universe", self.platform.universe_payload())
            await self.hub.broadcast(
                "system", self.platform.health.snapshot().model_dump(mode="json")
            )
        except Exception:  # noqa: BLE001 - a failed tick must not stop the loop
            logger.exception("quote job failed")

    async def _scan_job(self) -> None:
        try:
            result = await asyncio.to_thread(self.platform.refresh, True)
            await self.hub.broadcast("signals", _signals_payload(result))
            await self.hub.broadcast("universe", self.platform.universe_payload())
            await self.hub.broadcast("briefing", self.platform.briefing())
        except Exception:  # noqa: BLE001
            logger.exception("scan job failed")

    async def _ingest_job(self) -> None:
        try:
            tickers = self.platform.universe.tickers()
            await asyncio.to_thread(self.platform.ingest.ingest_all, tickers)
            logger.info("ingest refreshed at %s", datetime.now(UTC).isoformat())
        except Exception:  # noqa: BLE001
            logger.exception("ingest job failed")


def _signals_payload(result) -> dict:
    return {
        "generated_at": result.finished_at.isoformat(),
        "count": len(result.signals),
        "executable": len(result.executable),
        "signals": [
            {
                "signal_id": s.signal_id,
                "ticker": s.ticker,
                "strategy": s.strategy_id,
                "score": s.confidence,
                "technical": s.score.technical,
                "sentiment": s.score.sentiment,
                "fundamental": s.score.fundamental,
                "political": s.score.political,
                "entry": s.trade.entry,
                "stop": s.trade.stop,
                "target": s.trade.target,
                "reward_risk": s.trade.reward_risk,
                "sector": s.sector,
                "executable": s.execution.allowed,
                "reasons": [r.value for r in s.execution.reasons],
            }
            for s in result.signals[:60]
        ],
    }
