"""Risk validation and order execution.

The risk engine is independent of strategy logic by design (spec section 18): no
strategy can reach it, and it is the only path from a Signal to an Order.
"""

from trading_universe.execution.broker_base import BrokerBase
from trading_universe.execution.engine import ExecutionEngine
from trading_universe.execution.paper import PaperBroker
from trading_universe.execution.risk_engine import RiskContext, RiskEngine
from trading_universe.execution.sizing import size_position

__all__ = [
    "BrokerBase",
    "ExecutionEngine",
    "PaperBroker",
    "RiskContext",
    "RiskEngine",
    "size_position",
]
