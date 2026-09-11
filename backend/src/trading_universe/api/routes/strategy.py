"""Strategy selection and parameters (spec sections 6, 35, 67)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException

from trading_universe.api.deps import platform_dep
from trading_universe.services.platform import Platform
from trading_universe.strategies.registry import STRATEGY_BY_ID, strategy_labels

router = APIRouter(prefix="/api/strategy", tags=["strategy"])


@router.get("")
def list_strategies(platform: Platform = Depends(platform_dep)) -> dict:
    cfg = platform.config.strategies
    result = platform.scanner.last_result
    counts: dict[str, int] = {}
    for signal in result.signals if result else []:
        counts[signal.strategy_id] = counts.get(signal.strategy_id, 0) + 1

    gates = platform.health.strategy_gates()
    return {
        "active_strategy": platform.execution.active_strategy,
        "strategies": [
            {
                "id": sid,
                "label": cls.label,
                "kind": cls.kind.value,
                "enabled": cfg.strategy(sid).get("enabled", True),
                "minimum_score": cfg.minimum_score(sid),
                "config": cfg.strategy(sid),
                "signals_today": counts.get(sid, 0),
                "gate": gates.get(sid, "UNKNOWN"),
                "is_active": sid == platform.execution.active_strategy,
            }
            for sid, cls in STRATEGY_BY_ID.items()
        ],
    }


@router.get("/recommendation")
def recommendation(platform: Platform = Depends(platform_dep)) -> dict:
    result = platform.scanner.last_result
    if result is None or result.recommendation is None:
        raise HTTPException(404, "no recommendation yet - the first scan has not completed")
    rec = result.recommendation
    labels = strategy_labels()
    return {
        **rec.model_dump(mode="json"),
        "primary_strategy_label": labels.get(rec.primary_strategy, rec.primary_strategy),
        "alternatives": [
            {"strategy": sid, "label": labels.get(sid, sid), "fit": fit}
            for sid, fit in rec.alternatives
        ],
        "regime_inputs": result.regime.inputs.model_dump(mode="json") if result.regime else {},
        "active_strategy": platform.execution.active_strategy,
        "overridden": platform.execution.active_strategy not in (None, rec.primary_strategy),
    }


@router.get("/recommendation/history")
def recommendation_history(days: int = 60, platform: Platform = Depends(platform_dep)) -> dict:
    """Stored daily so the regime selector can be evaluated later (spec 6)."""
    return {"history": platform.repository.recommendation_history(days)}


@router.post("/accept")
def accept_recommendation(platform: Platform = Depends(platform_dep)) -> dict:
    result = platform.scanner.last_result
    if result is None or result.recommendation is None:
        raise HTTPException(404, "no recommendation to accept")
    rec = result.recommendation
    platform.execution.set_active_strategy(rec.primary_strategy)
    rec.accepted = True
    rec.overridden = False
    rec.active_strategy = rec.primary_strategy
    platform.repository.save_recommendation(rec)
    return {"active_strategy": rec.primary_strategy, "overridden": False}


@router.post("/override")
def override_strategy(
    strategy_id: str = Body(..., embed=True), platform: Platform = Depends(platform_dep)
) -> dict:
    """Manual override (spec section 6). The user always retains this.

    Other strategies keep scanning and keep appearing in the scanner and the
    universe; only the active one may execute automatically (spec 67).
    """
    if strategy_id not in STRATEGY_BY_ID and strategy_id != "NO_TRADE":
        raise HTTPException(400, f"unknown strategy: {strategy_id}")
    platform.execution.set_active_strategy(
        None if strategy_id == "NO_TRADE" else strategy_id
    )

    result = platform.scanner.last_result
    if result and result.recommendation:
        rec = result.recommendation
        rec.accepted = strategy_id == rec.primary_strategy
        rec.overridden = not rec.accepted
        rec.active_strategy = strategy_id
        platform.repository.save_recommendation(rec)

    return {
        "active_strategy": platform.execution.active_strategy,
        "overridden": True,
    }


@router.get("/sector-recommendations")
def sector_recommendations(platform: Platform = Depends(platform_dep)) -> dict:
    """Per-sector strategy preferences (spec section 68).

    In V1 these are advisory only: a single global strategy controls automatic
    execution. Sector-level execution permissions are a later step.
    """
    result = platform.scanner.last_result
    if result is None:
        return {"sectors": [], "note": "no scan yet"}
    labels = strategy_labels()
    return {
        "execution_model": "single global execution strategy; sector picks are advisory",
        "sectors": [
            {
                **s.model_dump(mode="json"),
                "recommended_strategy_label": labels.get(
                    s.recommended_strategy or "", s.recommended_strategy
                ),
            }
            for s in result.sector_regimes
        ],
    }


@router.get("/regime")
def regime(platform: Platform = Depends(platform_dep)) -> dict:
    result = platform.scanner.last_result
    if result is None or result.regime is None:
        raise HTTPException(404, "no regime computed yet")
    return result.regime.model_dump(mode="json")


@router.get("/today")
def today(platform: Platform = Depends(platform_dep)) -> dict:
    stored = platform.repository.get_recommendation(date.today())
    if stored is None:
        raise HTTPException(404, "no recommendation stored for today")
    return stored
