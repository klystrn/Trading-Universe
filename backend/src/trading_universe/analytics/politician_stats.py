"""Politician analytics (spec sections 16, 39).

Every statistic here is measured from the DISCLOSURE date forward. Measuring
from the transaction date would credit a politician with returns nobody could
have captured, which would be a fabricated track record.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from trading_universe.domain.political import PoliticalTransaction


def politician_leaderboard(
    transactions: list[PoliticalTransaction],
    forward_returns: dict[str, float] | None = None,
    min_disclosures: int = 3,
) -> list[dict[str, Any]]:
    """Rank disclosed accounts by post-disclosure follow-through.

    ``forward_returns`` maps transaction_id -> return measured from the
    disclosure date. When it is empty the leaderboard still reports activity but
    reports ``None`` for performance rather than zero, because no measurement has
    been made yet.
    """
    forward_returns = forward_returns or {}
    grouped: dict[str, list[PoliticalTransaction]] = defaultdict(list)
    for txn in transactions:
        grouped[txn.identity_key].append(txn)

    rows: list[dict[str, Any]] = []
    for key, txns in grouped.items():
        purchases = [t for t in txns if t.is_purchase]
        if len(txns) < min_disclosures:
            continue
        returns = [
            forward_returns[t.transaction_id]
            for t in purchases
            if t.transaction_id in forward_returns
        ]
        name, owner = key.split("|", 1)
        rows.append(
            {
                "politician": name,
                "owner": owner,
                "chamber": txns[0].chamber.value,
                "party": txns[0].party,
                "state": txns[0].state,
                "disclosed_purchases": len(purchases),
                "disclosed_sales": len(txns) - len(purchases),
                "distinct_tickers": len({t.ticker for t in txns}),
                "avg_disclosure_lag_days": round(
                    statistics.fmean([t.disclosure_lag_days for t in txns]), 1
                ),
                "total_disclosed_low": round(sum(t.amount_low for t in purchases), 2),
                "total_disclosed_high": round(sum(t.amount_high for t in purchases), 2),
                "measured_returns": len(returns),
                "avg_return_post_disclosure": (
                    round(statistics.fmean(returns), 5) if returns else None
                ),
                "follow_through_rate": (
                    round(sum(1 for r in returns if r > 0) / len(returns), 4)
                    if returns
                    else None
                ),
            }
        )

    rows.sort(
        key=lambda r: (
            r["avg_return_post_disclosure"] is not None,
            r["avg_return_post_disclosure"] or 0.0,
            r["disclosed_purchases"],
        ),
        reverse=True,
    )
    return rows


def ticker_consensus_table(transactions: list[PoliticalTransaction]) -> list[dict[str, Any]]:
    """Which names have the broadest disclosed buying."""
    grouped: dict[str, list[PoliticalTransaction]] = defaultdict(list)
    for txn in transactions:
        grouped[txn.ticker].append(txn)

    rows = []
    for ticker, txns in grouped.items():
        purchases = [t for t in txns if t.is_purchase]
        if not purchases:
            continue
        rows.append(
            {
                "ticker": ticker,
                "distinct_buyers": len({t.identity_key for t in purchases}),
                "purchases": len(purchases),
                "sales": len(txns) - len(purchases),
                "chambers": sorted({t.chamber.value for t in purchases}),
                "newest_disclosure": max(t.disclosure_date for t in purchases).isoformat(),
                "total_low": round(sum(t.amount_low for t in purchases), 2),
                "total_high": round(sum(t.amount_high for t in purchases), 2),
            }
        )
    rows.sort(key=lambda r: (r["distinct_buyers"], r["purchases"]), reverse=True)
    return rows


def disclosure_lag_stats(transactions: list[PoliticalTransaction]) -> dict[str, Any]:
    """How stale political data inherently is - the honest framing from spec 31."""
    if not transactions:
        return {"count": 0}
    lags = [t.disclosure_lag_days for t in transactions]
    return {
        "count": len(lags),
        "mean_lag_days": round(statistics.fmean(lags), 1),
        "median_lag_days": round(statistics.median(lags), 1),
        "max_lag_days": max(lags),
        "min_lag_days": min(lags),
    }
