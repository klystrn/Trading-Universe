"""SQLite persistence (spec section 23).

SQLite initially; the schema is deliberately plain so a later move to
PostgreSQL/TimescaleDB is a connection-string change plus a migration.
"""

from trading_universe.db.models import (
    Base,
    DailyRecommendationRow,
    OrderRow,
    PoliticalTransactionRow,
    SignalRow,
    ThesisRow,
    TradeRow,
    WatchlistRow,
)
from trading_universe.db.repository import Repository
from trading_universe.db.session import (
    get_engine,
    get_session,
    init_db,
    session_scope,
)

__all__ = [
    "Base",
    "DailyRecommendationRow",
    "OrderRow",
    "PoliticalTransactionRow",
    "Repository",
    "SignalRow",
    "ThesisRow",
    "TradeRow",
    "WatchlistRow",
    "get_engine",
    "get_session",
    "init_db",
    "session_scope",
]
