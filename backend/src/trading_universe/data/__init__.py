"""Data collection layer.

Nothing above this layer talks to an external service directly. Everything is
timestamped with both ``event_time`` and ``received_time`` so freshness is always
computable (spec section 28).
"""

from trading_universe.data.freshness import FreshnessService
from trading_universe.data.universe import UniverseRegistry, get_universe

__all__ = ["FreshnessService", "UniverseRegistry", "get_universe"]
