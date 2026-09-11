"""WebSocket endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from trading_universe.api.deps import hub_dep, platform_dep
from trading_universe.services.platform import Platform
from trading_universe.websocket.hub import CHANNELS, WebSocketHub

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    channels: str = Query(default="universe,signals,system,briefing"),
    hub: WebSocketHub = Depends(hub_dep),
    platform: Platform = Depends(platform_dep),
) -> None:
    requested = [c.strip() for c in channels.split(",") if c.strip() in CHANNELS]
    await hub.connect(websocket, requested or list(CHANNELS))
    try:
        while True:
            # The client does not need to send anything; this keeps the socket
            # open and lets a client request an immediate refresh.
            message = await websocket.receive_text()
            if message.strip() == "refresh":
                if "universe" in requested:
                    await hub.broadcast("universe", platform.universe_payload())
                if "system" in requested:
                    await hub.broadcast(
                        "system", platform.health.snapshot().model_dump(mode="json")
                    )
                if "briefing" in requested:
                    await hub.broadcast("briefing", platform.briefing())
    except WebSocketDisconnect:
        await hub.disconnect(websocket)
    except Exception:  # noqa: BLE001
        logger.debug("websocket closed unexpectedly", exc_info=True)
        await hub.disconnect(websocket)
