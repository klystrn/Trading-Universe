"""FastAPI application factory."""

from __future__ import annotations

import asyncio
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

# Routes that must answer while the first scan is still running: the hosting
# provider's health check and the HUD's "how far along are you" poll.
WARM_UP_ALLOWED = frozenset({"/api/system/status"})


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
    scheduler = SchedulerService(platform, hub)
    app.state.platform = platform
    app.state.scheduler = scheduler

    async def warm_up() -> None:
        # Bootstrap off the event loop: warming 477 candle series and the first
        # scan takes seconds locally and far longer on a small cloud CPU.
        await asyncio.to_thread(platform.bootstrap)
        await hub.broadcast("briefing", platform.briefing())
        await hub.broadcast("system", platform.health.snapshot().model_dump(mode="json"))
        scheduler.start()

    if settings.bootstrap_in_background:
        # Serve the HUD and /api/system/status immediately so a cold-started
        # deployment shows "warming up" instead of a hosting provider's spinner;
        # every other /api route answers 503 until the first scan lands.
        warm_task = asyncio.create_task(warm_up(), name="bootstrap")
    else:
        await warm_up()
        warm_task = None

    try:
        yield
    finally:
        if warm_task is not None and not warm_task.done():
            warm_task.cancel()
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

    @app.middleware("http")
    async def _warm_up_guard(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path not in WARM_UP_ALLOWED:
            platform = get_platform()
            if not platform.bootstrapped:
                return JSONResponse(
                    status_code=503,
                    headers={"Retry-After": "3"},
                    content={
                        "detail": "warming up",
                        "stage": platform.bootstrap_stage,
                        "error": platform.bootstrap_error,
                    },
                )
        return await call_next(request)

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
