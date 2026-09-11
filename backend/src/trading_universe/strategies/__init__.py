"""Strategy engine.

Strategies never place orders and never assign their own scores. Each returns a
:class:`StrategyEvaluation`; the scoring layer weights it and the risk engine
decides whether it may execute.
"""

from trading_universe.strategies.base import (
    Strategy,
    StrategyContext,
    StrategyEvaluation,
    StrategyProposal,
)
from trading_universe.strategies.registry import (
    STRATEGY_BY_ID,
    build_strategies,
    build_strategy,
    strategy_labels,
)

__all__ = [
    "STRATEGY_BY_ID",
    "Strategy",
    "StrategyContext",
    "StrategyEvaluation",
    "StrategyProposal",
    "build_strategies",
    "build_strategy",
    "strategy_labels",
]
