"""Floating search bar: entity lookup and market questions (spec section 43)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from trading_universe.api.deps import platform_dep
from trading_universe.services.platform import Platform
from trading_universe.services.questions import answer_question
from trading_universe.strategies.registry import strategy_labels

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
def search(
    q: str = Query(..., min_length=1),
    limit: int = 12,
    platform: Platform = Depends(platform_dep),
) -> dict:
    """Entity search across tickers, company names, sectors and subsectors."""
    query = q.strip().lower()
    results: list[dict[str, Any]] = []

    for sector_id, sector in platform.universe.sectors.items():
        if query in sector_id.lower() or query in sector.label.lower():
            results.append(
                {
                    "type": "sector",
                    "id": sector_id,
                    "label": sector.label,
                    "sublabel": f"{len(platform.universe.by_sector(sector_id))} companies",
                    "score": 0 if sector.label.lower().startswith(query) else 1,
                }
            )

    seen_subsectors: set[str] = set()
    for sub_id, sub in platform.universe.subsectors.items():
        if query in sub.label.lower() and sub.label not in seen_subsectors:
            seen_subsectors.add(sub.label)
            results.append(
                {
                    "type": "subsector",
                    "id": sub_id,
                    "label": sub.label,
                    "sublabel": platform.universe.sectors[sub.sector_id].label,
                    "score": 0 if sub.label.lower().startswith(query) else 1,
                }
            )

    for ticker, stock in platform.universe.stocks.items():
        ticker_match = query in ticker.lower()
        name_match = query in stock.name.lower()
        if not (ticker_match or name_match):
            continue
        results.append(
            {
                "type": "stock",
                "id": ticker,
                "label": ticker,
                "sublabel": stock.name,
                "sector": stock.sector,
                # Exact ticker first, then prefix matches, then substrings.
                "score": (
                    -1 if ticker.lower() == query
                    else 0 if ticker.lower().startswith(query)
                    else 1 if name_match and stock.name.lower().startswith(query)
                    else 2
                ),
            }
        )

    results.sort(key=lambda r: (r["score"], r["label"]))
    return {"query": q, "results": results[:limit]}


@router.get("/ask")
def ask(
    q: str = Query(..., min_length=3), platform: Platform = Depends(platform_dep)
) -> dict:
    """Natural-language market questions (spec section 43).

    Answered from the platform's own live state by a deterministic intent
    matcher - no external model, so every answer is traceable to data the
    system actually holds. Unrecognised questions say so rather than
    improvising.
    """
    return answer_question(q, platform, strategy_labels())
