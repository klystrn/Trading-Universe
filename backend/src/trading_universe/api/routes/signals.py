"""Scanner / signals endpoints (spec section 40)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from trading_universe.api.deps import platform_dep
from trading_universe.services.platform import Platform
from trading_universe.strategies.registry import strategy_labels

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("")
def list_signals(
    strategy: str | None = None,
    sector: str | None = None,
    min_score: float | None = None,
    executable_only: bool = False,
    limit: int = Query(default=100, le=500),
    platform: Platform = Depends(platform_dep),
) -> dict:
    result = platform.scanner.last_result
    if result is None:
        return {"signals": [], "count": 0, "generated_at": None}

    labels = strategy_labels()
    signals = result.signals
    if strategy:
        signals = [s for s in signals if s.strategy_id == strategy]
    if sector:
        signals = [s for s in signals if s.sector == sector]
    if min_score is not None:
        signals = [s for s in signals if s.score.total >= min_score]
    if executable_only:
        signals = [s for s in signals if s.execution.allowed]

    return {
        "generated_at": result.finished_at.isoformat(),
        "count": len(signals),
        "active_strategy": platform.execution.active_strategy,
        "signals": [
            {
                **s.model_dump(mode="json"),
                "strategy_label": labels.get(s.strategy_id, s.strategy_id),
                # Regime match is how well the strategy fits today, which is not
                # the same as the signal's own score.
                "regime_match": s.market.strategy_match,
                "tier": platform.market_data.tier_of(s.ticker),
            }
            for s in signals[:limit]
        ],
    }


@router.get("/rejected")
def rejected(
    limit: int = Query(default=100, le=500), platform: Platform = Depends(platform_dep)
) -> dict:
    """Rejected signals, with reasons. The UI explains rejections rather than
    silently dropping them (spec section 76)."""
    rows = platform.repository.rejected_signals(limit)
    return {"count": len(rows), "signals": rows}


@router.get("/history")
def history(
    strategy: str | None = None,
    min_score: float | None = None,
    limit: int = Query(default=200, le=1000),
    platform: Platform = Depends(platform_dep),
) -> dict:
    rows = platform.repository.recent_signals(
        limit=limit, strategy_id=strategy, min_score=min_score
    )
    return {"count": len(rows), "signals": rows}


@router.get("/{signal_id}/thesis")
def thesis(signal_id: str, platform: Platform = Depends(platform_dep)) -> dict:
    payload = platform.repository.thesis_for_signal(signal_id)
    if payload is None:
        raise HTTPException(404, "no thesis recorded for that signal")
    return payload


@router.get("/near-misses")
def near_misses(
    limit: int = Query(default=50, le=200), platform: Platform = Depends(platform_dep)
) -> dict:
    """Setups that failed only one or two checks - the 'why not' list."""
    result = platform.scanner.last_result
    if result is None:
        return {"count": 0, "near_misses": []}
    return {
        "count": len(result.near_misses),
        "near_misses": [
            {
                "ticker": e.ticker,
                "strategy": e.strategy_id,
                "failed": e.failed_checks,
                "passed": e.passed_checks,
            }
            for e in result.near_misses[:limit]
        ],
    }
