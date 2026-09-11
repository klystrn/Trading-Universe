"""Trade log (spec section 36)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from trading_universe.api.deps import platform_dep
from trading_universe.services.platform import Platform
from trading_universe.strategies.registry import strategy_labels

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("")
def list_trades(
    strategy: str | None = None,
    ticker: str | None = None,
    sector: str | None = None,
    result: str | None = None,
    paper: bool | None = None,
    execution_source: str | None = None,
    days: int | None = None,
    limit: int = Query(default=200, le=1000),
    platform: Platform = Depends(platform_dep),
) -> dict:
    since = datetime.now(UTC) - timedelta(days=days) if days else None
    rows = platform.repository.list_trades(
        limit=limit, strategy_id=strategy, ticker=ticker, sector=sector,
        result=result, paper=paper, execution_source=execution_source, since=since,
    )
    labels = strategy_labels()
    for row in rows:
        row["strategy_label"] = labels.get(row["strategy_id"], row["strategy_id"])
    return {"count": len(rows), "trades": rows}


@router.get("/{trade_id}/thesis")
def trade_thesis(trade_id: str, platform: Platform = Depends(platform_dep)) -> dict:
    payload = platform.repository.get_thesis(trade_id)
    if payload is None:
        raise HTTPException(404, "no thesis recorded for that trade")
    return payload


@router.get("/filters/options")
def filter_options(platform: Platform = Depends(platform_dep)) -> dict:
    """Populate the trade-log filter controls."""
    return {
        "strategies": [
            {"id": sid, "label": label} for sid, label in strategy_labels().items()
        ],
        "sectors": [
            {"id": s.id, "label": s.label} for s in platform.universe.sectors.values()
        ],
        "results": ["OPEN", "WIN", "LOSS", "BREAKEVEN"],
        "execution_sources": ["AUTO", "MANUAL", "RECOMMENDED_ACCEPTED", "MANUAL_OVERRIDE"],
    }
