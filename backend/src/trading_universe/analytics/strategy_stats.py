"""Per-strategy and per-dimension performance breakdowns (spec sections 41, 70)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from trading_universe.analytics.performance import compute_metrics
from trading_universe.strategies.registry import strategy_labels


def breakdown_by(trades: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    """Group trades by a field and compute metrics for each group."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        groups[str(trade.get(key) or "unknown")].append(trade)
    return {name: compute_metrics(rows).to_dict() for name, rows in groups.items()}


def strategy_table(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The Portfolio tab's strategy table (spec section 41)."""
    labels = strategy_labels()
    rows = []
    for strategy_id, metrics in breakdown_by(trades, "strategy_id").items():
        rows.append(
            {
                "strategy": strategy_id,
                "label": labels.get(strategy_id, strategy_id),
                "trades": metrics["closed"],
                "win_rate": metrics["win_rate"],
                "avg_r": metrics["avg_r"],
                "expectancy_r": metrics["expectancy_r"],
                "profit_factor": metrics["profit_factor"],
                "pnl": metrics["total_pnl"],
                "avg_holding_days": metrics["avg_holding_days"],
            }
        )
    rows.sort(key=lambda r: (r["trades"], r["avg_r"] or 0.0), reverse=True)
    return rows


def avg_r_by_strategy(trades: list[dict[str, Any]]) -> dict[str, float]:
    """Feeds the regime selector's performance tilt. Only strategies with enough
    closed trades are included - tilting on a two-trade sample is noise."""
    out: dict[str, float] = {}
    for strategy_id, metrics in breakdown_by(trades, "strategy_id").items():
        if metrics["closed"] >= 10 and metrics["avg_r"] is not None:
            out[strategy_id] = metrics["avg_r"]
    return out


def regime_performance(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Did the regime selector help? This is the table that answers it."""
    return breakdown_by(trades, "market_regime")


def sector_performance(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return breakdown_by(trades, "sector")


def source_performance(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Automated vs manual vs override."""
    return breakdown_by(trades, "execution_source")
