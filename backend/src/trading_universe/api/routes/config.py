"""Live configuration editing (spec sections 3, 35, 66).

The UI sliders write here. Values are validated, applied in memory immediately,
and persisted so a restart keeps them.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from trading_universe.api.deps import platform_dep
from trading_universe.services.platform import Platform

router = APIRouter(prefix="/api/config", tags=["config"])

# Guard rails for anything the UI can change. A slider must not be able to set
# max_position_value to 1e9 or a reward:risk of 0.
BOUNDS: dict[str, tuple[float, float]] = {
    "minimum_reward_risk": (1.0, 10.0),
    "max_position_value": (5.0, 100_000.0),
    "max_new_trades_per_day": (0, 50),
    "max_open_positions": (0, 50),
    "min_score_standard": (0, 100),
    "min_score_political": (0, 100),
    "liquidity.min_avg_dollar_volume_20d": (0, 1e12),
    "liquidity.min_avg_share_volume_20d": (0, 1e10),
    "liquidity.max_spread_pct": (0.0, 0.5),
    "liquidity.min_price": (0.0, 10_000.0),
    "orders.min_notional": (0.0, 10_000.0),
    "orders.max_entry_drift_pct": (0.0, 0.5),
    "orders.duplicate_window_seconds": (0, 86_400),
    "loss_streak_guard.consecutive_losses": (1, 20),
}


@router.get("")
def get_config(platform: Platform = Depends(platform_dep)) -> dict:
    return platform.config.as_dict()


@router.get("/risk")
def get_risk(platform: Platform = Depends(platform_dep)) -> dict:
    return platform.config.risk.data


@router.patch("/risk")
def patch_risk(
    updates: dict[str, Any] = Body(...), platform: Platform = Depends(platform_dep)
) -> dict:
    """Apply dotted-path updates, e.g. {"max_position_value": 200}."""
    risk = platform.config.risk
    applied: dict[str, Any] = {}

    for path, value in updates.items():
        if path in BOUNDS:
            low, high = BOUNDS[path]
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise HTTPException(400, f"{path} must be numeric") from exc
            if not (low <= numeric <= high):
                raise HTTPException(
                    400, f"{path} must be between {low} and {high} (got {numeric})"
                )
            value = int(numeric) if float(numeric).is_integer() and "pct" not in path \
                and "reward" not in path else numeric
        risk.set(path, value)
        applied[path] = value

    risk.save()
    return {"applied": applied, "risk": risk.data}


@router.get("/strategies")
def get_strategies(platform: Platform = Depends(platform_dep)) -> dict:
    return platform.config.strategies.data


@router.patch("/strategies/{strategy_id}")
def patch_strategy(
    strategy_id: str,
    updates: dict[str, Any] = Body(...),
    platform: Platform = Depends(platform_dep),
) -> dict:
    """Update one strategy's parameters. Strategies are rebuilt from config on
    every scan, so this takes effect on the next cycle without a restart."""
    cfg = platform.config.strategies
    if strategy_id not in cfg.all_strategy_ids():
        raise HTTPException(404, f"unknown strategy: {strategy_id}")

    for path, value in updates.items():
        cfg.set(f"strategies.{strategy_id}.{path}", value)
    cfg.save()
    return {"strategy": strategy_id, "config": cfg.strategy(strategy_id)}


@router.get("/freshness")
def get_freshness(platform: Platform = Depends(platform_dep)) -> dict:
    return platform.config.freshness.data


@router.patch("/freshness")
def patch_freshness(
    updates: dict[str, Any] = Body(...), platform: Platform = Depends(platform_dep)
) -> dict:
    cfg = platform.config.freshness
    for path, value in updates.items():
        cfg.set(path, value)
    cfg.save()
    return cfg.data


@router.post("/reload")
def reload_config(platform: Platform = Depends(platform_dep)) -> dict:
    platform.config.reload()
    return {"reloaded": True, "config": platform.config.as_dict()}
