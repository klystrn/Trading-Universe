"""WebSocket hub (spec section 25).

Pushes a COMPACT visualization payload, never the full financial state on every
frame (spec section 77). Three channels:

    universe  - per-entity visual state, throttled
    signals   - new/changed signals
    system    - health, freshness, execution state
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

CHANNELS = ("universe", "signals", "system", "briefing")


class WebSocketHub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._last: dict[str, dict[str, Any]] = {}

    async def connect(self, websocket: WebSocket, channels: list[str]) -> None:
        await websocket.accept()
        async with self._lock:
            for channel in channels:
                if channel in CHANNELS:
                    self._subscribers[channel].add(websocket)
        # Replay the most recent payload so a new client is not blank until the
        # next scheduled push.
        for channel in channels:
            cached = self._last.get(channel)
            if cached is not None:
                await self._send(websocket, channel, cached)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            for subscribers in self._subscribers.values():
                subscribers.discard(websocket)

    async def broadcast(self, channel: str, payload: dict[str, Any]) -> int:
        if channel not in CHANNELS:
            raise ValueError(f"unknown channel: {channel}")
        self._last[channel] = payload

        async with self._lock:
            targets = list(self._subscribers[channel])
        if not targets:
            return 0

        dead: list[WebSocket] = []
        sent = 0
        for websocket in targets:
            try:
                await self._send(websocket, channel, payload)
                sent += 1
            except Exception:  # noqa: BLE001 - a dropped client is routine
                dead.append(websocket)
        if dead:
            async with self._lock:
                for websocket in dead:
                    for subscribers in self._subscribers.values():
                        subscribers.discard(websocket)
        return sent

    @staticmethod
    async def _send(websocket: WebSocket, channel: str, payload: dict[str, Any]) -> None:
        await websocket.send_text(
            json.dumps(
                {
                    "channel": channel,
                    "at": datetime.now(UTC).isoformat(),
                    "data": payload,
                },
                default=str,
            )
        )

    def subscriber_count(self, channel: str | None = None) -> int:
        if channel:
            return len(self._subscribers[channel])
        return len({ws for subs in self._subscribers.values() for ws in subs})


_hub: WebSocketHub | None = None


def get_hub() -> WebSocketHub:
    global _hub
    if _hub is None:
        _hub = WebSocketHub()
    return _hub
