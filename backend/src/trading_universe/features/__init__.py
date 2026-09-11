"""Feature generation layer.

Turns raw data objects into the timestamped snapshots strategies reason about.
Nothing here knows what a strategy is, and nothing here places an order.
"""

from trading_universe.features.fundamentals import build_fundamental_snapshot, quality_score
from trading_universe.features.political import build_political_snapshot
from trading_universe.features.sentiment import (
    SentimentEngine,
    build_sentiment_snapshot,
    get_sentiment_engine,
)
from trading_universe.features.technical import build_technical_snapshot

__all__ = [
    "SentimentEngine",
    "build_fundamental_snapshot",
    "build_political_snapshot",
    "build_sentiment_snapshot",
    "build_technical_snapshot",
    "get_sentiment_engine",
    "quality_score",
]
