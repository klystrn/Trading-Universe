"""Portfolio endpoints (spec section 41)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from trading_universe.api.deps import platform_dep
from trading_universe.services.platform import Platform
from trading_universe.strategies.registry import strategy_labels

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("")
def portfolio(platform: Platform = Depends(platform_dep)) -> dict:
    pf = platform.broker.get_portfolio()
    risk = platform.config.risk
    pf.max_open_positions = risk.max_open_positions
    pf.max_new_trades_per_day = risk.max_new_trades_per_day

    prices = platform.market_data.prices()
    for position in pf.positions:
        price = prices.get(position.ticker)
        if price:
            position.current_price = price

    labels = strategy_labels()
    return {
        **pf.model_dump(mode="json"),
        "sector_exposure": pf.sector_exposure(platform.universe.sector_map()),
        "strategy_exposure": {
            labels.get(k, k): v for k, v in pf.strategy_exposure().items()
        },
        "broker": platform.broker.name,
        "paper": platform.broker.paper,
        "positions": [
            {
                **p.model_dump(mode="json"),
                "sector": platform.universe.sector_of(p.ticker),
                "name": (
                    platform.universe.get(p.ticker).name
                    if platform.universe.get(p.ticker)
                    else p.ticker
                ),
                "strategy_label": labels.get(p.strategy_id or "", p.strategy_id),
            }
            for p in pf.positions
        ],
    }


@router.get("/orders")
def orders(limit: int = 100, platform: Platform = Depends(platform_dep)) -> dict:
    return {"orders": platform.repository.list_orders(limit)}


@router.get("/open-orders")
def open_orders(platform: Platform = Depends(platform_dep)) -> dict:
    return {
        "orders": [o.model_dump(mode="json") for o in platform.broker.get_open_orders()]
    }


@router.get("/capacity")
def capacity(platform: Platform = Depends(platform_dep)) -> dict:
    """What the user needs to answer 'how many more trades can I open?'."""
    pf = platform.broker.get_portfolio()
    risk = platform.config.risk
    trades_today = getattr(platform.broker, "trades_opened_today", lambda: 0)()
    return {
        "open_positions": len(pf.positions),
        "max_open_positions": risk.max_open_positions,
        "remaining_position_slots": max(0, risk.max_open_positions - len(pf.positions)),
        "trades_opened_today": trades_today,
        "max_new_trades_per_day": risk.max_new_trades_per_day,
        "remaining_daily_entries": max(0, risk.max_new_trades_per_day - trades_today),
        "max_position_value": risk.max_position_value,
        "consecutive_losses": getattr(platform.broker, "consecutive_losses", lambda: 0)(),
        "kill_switch_engaged": risk.kill_switch_engaged,
    }
