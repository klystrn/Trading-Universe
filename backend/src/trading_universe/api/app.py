"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from trading_universe.api.routes import (
    analytics,
    health,
    political,
    portfolio,
    search,
    signals,
    strategy,
    trades,
    universe,
    watchlist,
    websocket_routes,
)
from trading_universe.api.routes import (
    config as config_routes,
)
from trading_universe.services.platform import get_platform
from trading_universe.services.scheduler import SchedulerService
from trading_universe.settings import get_settings, real_order_warning
from trading_universe.websocket.hub import get_hub

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    warning = real_order_warning()
    if warning:
        logger.warning("=" * 78)
        logger.warning(warning)
        logger.warning("=" * 78)

    logger.info(
        "Trading Universe starting: mode=%s data=%s env=%s",
        settings.operating_mode.value, settings.data_mode.value, settings.trading_env,
    )

    platform = get_platform()
    hub = get_hub()
    import asyncio

    # Bootstrap off the event loop: warming 477 candle series and the first scan
    # takes seconds, and blocking startup would stall every health probe.
    await asyncio.to_thread(platform.bootstrap)
    await hub.broadcast("briefing", platform.briefing())

    scheduler = SchedulerService(platform, hub)
    scheduler.start()
    app.state.platform = platform
    app.state.scheduler = scheduler

    try:
        yield
    finally:
        scheduler.shutdown()
        platform.shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Trading Universe API",
        version="0.1.0",
        description=(
            "A swing-trading bot whose interface is a navigable financial "
            "universe. Strategies propose; the risk engine disposes."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in (
        health.router,
        universe.router,
        signals.router,
        strategy.router,
        portfolio.router,
        trades.router,
        political.router,
        watchlist.router,
        analytics.router,
        config_routes.router,
        search.router,
        websocket_routes.router,
    ):
        app.include_router(router)

    if settings.read_only:
        logger.warning("TU_READ_ONLY=true: all mutating API calls will be refused")

        @app.middleware("http")
        async def _read_only_guard(request: Request, call_next):
            if request.method in ("POST", "PUT", "PATCH", "DELETE") and (
                request.url.path.startswith("/api/")
            ):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "This is a shared read-only demo; settings, modes and "
                        "orders cannot be changed here. Run it locally to trade."
                    },
                )
            return await call_next(request)

    static_dir = settings.resolved_static_dir
    if static_dir is not None:
        # Mounted last so /api, /ws and /docs keep precedence. html=True serves
        # index.html for "/", which is the entire single-page frontend.
        logger.info("serving frontend from %s", static_dir)
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="frontend")
    else:
        @app.get("/", tags=["meta"])
        def root() -> dict[str, str]:
            return {
                "name": "Trading Universe",
                "version": "0.1.0",
                "docs": "/docs",
                "frontend": "not bundled - run `npm run dev` in frontend/, or build a "
                "static export (see README: Shareable demo)",
            }

    return app


app = create_app()
