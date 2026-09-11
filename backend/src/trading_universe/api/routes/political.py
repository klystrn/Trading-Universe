"""Politician trade monitoring (spec section 39)."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query

from trading_universe.analytics.politician_stats import (
    disclosure_lag_stats,
    politician_leaderboard,
    ticker_consensus_table,
)
from trading_universe.api.deps import platform_dep
from trading_universe.services.platform import Platform

router = APIRouter(prefix="/api/political", tags=["political"])


@router.get("/transactions")
def transactions(
    ticker: str | None = None,
    politician: str | None = None,
    chamber: str | None = None,
    party: str | None = None,
    state: str | None = None,
    transaction_type: str | None = None,
    min_amount: float | None = None,
    disclosed_within_days: int | None = None,
    limit: int = Query(default=200, le=1000),
    platform: Platform = Depends(platform_dep),
) -> dict:
    since = (
        date.today() - timedelta(days=disclosed_within_days)
        if disclosed_within_days
        else None
    )
    rows = platform.repository.list_political(
        limit=limit, ticker=ticker, politician=politician, chamber=chamber,
        party=party, state=state, transaction_type=transaction_type,
        min_amount=min_amount, disclosed_since=since,
    )
    # Attach the sector so the tab can group and the universe can highlight.
    for row in rows:
        row["sector"] = platform.universe.sector_of(row["ticker"])
        row["in_universe"] = platform.universe.get(row["ticker"]) is not None
    return {"count": len(rows), "transactions": rows}


@router.get("/summary")
def summary(platform: Platform = Depends(platform_dep)) -> dict:
    txns = platform.repository.load_political_domain()
    return {
        **platform.repository.political_summary(),
        "disclosure_lag": disclosure_lag_stats(txns),
        # This is the honest framing from spec 31: political data is never
        # real-time, because disclosure trails the transaction.
        "note": (
            "All windows are measured from the DISCLOSURE date, never the "
            "transaction date, so no signal uses information that was not public."
        ),
    }


@router.get("/consensus")
def consensus(platform: Platform = Depends(platform_dep)) -> dict:
    txns = platform.repository.load_political_domain(days=90)
    return {"tickers": ticker_consensus_table(txns)[:50]}


@router.get("/politicians")
def politicians(
    min_disclosures: int = 3, platform: Platform = Depends(platform_dep)
) -> dict:
    txns = platform.repository.load_political_domain()
    return {"politicians": politician_leaderboard(txns, min_disclosures=min_disclosures)}


@router.get("/snapshots")
def snapshots(platform: Platform = Depends(platform_dep)) -> dict:
    """Per-ticker aggregated political state, as the strategies see it."""
    data = platform.features.politicals(platform.universe.tickers())
    return {
        "count": len(data),
        "snapshots": [
            s.model_dump(mode="json")
            for s in sorted(
                data.values(), key=lambda s: s.consensus_score, reverse=True
            )
        ],
    }
