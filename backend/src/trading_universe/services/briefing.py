"""The daily briefing (spec section 63)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from trading_universe.services.scanner import ScanResult
from trading_universe.strategies.registry import strategy_labels


def build_briefing(
    scan: ScanResult | None, portfolio, political_summary: dict[str, Any] | None = None
) -> dict[str, Any]:
    labels = strategy_labels()
    now = datetime.now(UTC)

    if scan is None or scan.regime is None:
        return {
            "as_of": now.isoformat(),
            "market_regime": "UNKNOWN",
            "primary_strategy": None,
            "primary_strategy_label": None,
            "confidence": 0.0,
            "rationale": ["no scan has completed yet"],
            "strongest_sectors": [],
            "weakest_sectors": [],
            "high_confidence_signals": [],
            "political_activity": political_summary or {},
            "portfolio": _portfolio_summary(portfolio),
        }

    ranked_sectors = sorted(
        scan.sector_regimes, key=lambda s: s.relative_strength, reverse=True
    )
    primary = scan.recommendation.primary_strategy if scan.recommendation else None

    return {
        "as_of": now.isoformat(),
        "market_regime": scan.regime.regime.value,
        "regime_confidence": scan.regime.confidence,
        "primary_strategy": primary,
        "primary_strategy_label": labels.get(primary or "", primary),
        "confidence": scan.recommendation.confidence if scan.recommendation else 0.0,
        "rationale": scan.recommendation.rationale if scan.recommendation else [],
        "strongest_sectors": [
            {
                "sector": s.sector_id,
                "relative_strength": s.relative_strength,
                "label": s.rs_label,
                "recommended_strategy": s.recommended_strategy,
            }
            for s in ranked_sectors[:3]
        ],
        "weakest_sectors": [
            {
                "sector": s.sector_id,
                "relative_strength": s.relative_strength,
                "label": s.rs_label,
            }
            for s in ranked_sectors[-2:]
        ],
        "high_confidence_signals": [
            {
                "ticker": s.ticker,
                "score": s.confidence,
                "strategy": s.strategy_id,
                "strategy_label": labels.get(s.strategy_id, s.strategy_id),
                "executable": s.execution.allowed,
            }
            for s in scan.signals[:5]
        ],
        "signal_counts": {
            "total": len(scan.signals),
            "executable": len(scan.executable),
            "rejected": scan.rejected_count,
        },
        "political_activity": political_summary or {},
        "portfolio": _portfolio_summary(portfolio),
    }


def _portfolio_summary(portfolio) -> dict[str, Any]:
    if portfolio is None:
        return {}
    return {
        "open_positions": portfolio.open_position_count,
        "max_open_positions": portfolio.max_open_positions,
        "remaining_position_slots": portfolio.remaining_position_slots,
        "remaining_daily_entries": portfolio.remaining_daily_entries,
        "portfolio_value": portfolio.portfolio_value,
        "cash": portfolio.cash,
        "unrealized_pnl": portfolio.unrealized_pnl,
        "realized_pnl_today": portfolio.realized_pnl_today,
    }
