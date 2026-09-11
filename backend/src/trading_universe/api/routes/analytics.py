"""Analytics endpoints (spec sections 21, 41, 70)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from trading_universe.analytics.performance import compute_metrics, equity_curve
from trading_universe.analytics.rejected_signals import (
    near_miss_summary,
    rejection_breakdown,
    threshold_analysis,
)
from trading_universe.analytics.strategy_stats import (
    regime_performance,
    sector_performance,
    source_performance,
    strategy_table,
)
from trading_universe.api.deps import platform_dep
from trading_universe.services.platform import Platform

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/performance")
def performance(platform: Platform = Depends(platform_dep)) -> dict:
    trades = platform.repository.list_trades(limit=5000)
    metrics = compute_metrics(trades)
    return {
        "overall": metrics.to_dict(),
        "by_strategy": strategy_table(trades),
        "by_regime": regime_performance(trades),
        "by_sector": sector_performance(trades),
        "by_source": source_performance(trades),
        "equity_curve": equity_curve(trades),
    }


@router.get("/rejected")
def rejected(platform: Platform = Depends(platform_dep)) -> dict:
    """Why signals were turned down, and whether the thresholds are right."""
    signals = platform.repository.recent_signals(limit=5000)
    threshold = platform.config.risk.min_score_standard
    return {
        "breakdown": rejection_breakdown(signals),
        "threshold_analysis": threshold_analysis(signals),
        "near_misses": near_miss_summary(signals, threshold)[:50],
        "note": (
            "Forward returns are backfilled as history accumulates; buckets with "
            "measured=0 have no verdict yet."
        ),
    }


@router.get("/summary")
def summary(platform: Platform = Depends(platform_dep)) -> dict:
    trades = platform.repository.list_trades(limit=5000)
    signals = platform.repository.recent_signals(limit=2000)
    metrics = compute_metrics(trades)
    return {
        "trades": metrics.to_dict(),
        "signals_recorded": len(signals),
        "signals_accepted": sum(1 for s in signals if s.get("allowed")),
        "last_scan": platform.repository.last_scan(),
    }
