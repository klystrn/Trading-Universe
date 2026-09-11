"""Shared FastAPI dependencies."""

from __future__ import annotations

from trading_universe.services.platform import Platform, get_platform
from trading_universe.websocket.hub import WebSocketHub, get_hub


def platform_dep() -> Platform:
    return get_platform()


def hub_dep() -> WebSocketHub:
    return get_hub()
