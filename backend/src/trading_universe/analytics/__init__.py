"""Performance analytics (spec sections 21, 39, 70).

Everything here is descriptive. No analytic feeds back into strategy logic in
V1; the dataset it produces is the precondition for statistical strategy
selection later (spec 71).
"""

from trading_universe.analytics.performance import (
    PerformanceMetrics,
    compute_metrics,
    equity_curve,
)
from trading_universe.analytics.politician_stats import politician_leaderboard
from trading_universe.analytics.rejected_signals import (
    rejection_breakdown,
    threshold_analysis,
)
from trading_universe.analytics.strategy_stats import (
    breakdown_by,
    strategy_table,
)

__all__ = [
    "PerformanceMetrics",
    "breakdown_by",
    "compute_metrics",
    "equity_curve",
    "politician_leaderboard",
    "rejection_breakdown",
    "strategy_table",
    "threshold_analysis",
]
