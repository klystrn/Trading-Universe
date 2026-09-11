"""Core performance metrics (spec section 70)."""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class PerformanceMetrics:
    trades: int = 0
    closed: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float | None = None
    avg_r: float | None = None
    median_r: float | None = None
    profit_factor: float | None = None
    expectancy_r: float | None = None
    total_pnl: float = 0.0
    avg_win_r: float | None = None
    avg_loss_r: float | None = None
    max_drawdown: float | None = None
    sharpe_like: float | None = None
    avg_holding_days: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _r_multiples(trades: list[dict[str, Any]]) -> list[float]:
    return [
        float(t["r_multiple"])
        for t in trades
        if t.get("r_multiple") is not None and t.get("closed_at")
    ]


def compute_metrics(trades: list[dict[str, Any]]) -> PerformanceMetrics:
    """Metrics over a list of trade rows (as returned by the repository)."""
    metrics = PerformanceMetrics(trades=len(trades))
    closed = [t for t in trades if t.get("closed_at")]
    metrics.closed = len(closed)
    if not closed:
        return metrics

    rs = _r_multiples(closed)
    pnls = [float(t["realized_pnl"]) for t in closed if t.get("realized_pnl") is not None]
    metrics.total_pnl = round(sum(pnls), 4)

    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    metrics.wins = len(wins)
    metrics.losses = len(losses)

    if rs:
        metrics.win_rate = round(len(wins) / len(rs), 4)
        metrics.avg_r = round(statistics.fmean(rs), 4)
        metrics.median_r = round(statistics.median(rs), 4)
        metrics.avg_win_r = round(statistics.fmean(wins), 4) if wins else None
        metrics.avg_loss_r = round(statistics.fmean(losses), 4) if losses else None

        # Expectancy in R: what one unit of risk is worth per trade.
        if metrics.win_rate is not None and wins and losses:
            metrics.expectancy_r = round(
                metrics.win_rate * metrics.avg_win_r
                + (1 - metrics.win_rate) * metrics.avg_loss_r,
                4,
            )
        elif wins and not losses:
            metrics.expectancy_r = metrics.avg_win_r

        gross_win = sum(wins)
        gross_loss = abs(sum(losses))
        metrics.profit_factor = (
            round(gross_win / gross_loss, 4) if gross_loss > 0
            else (float("inf") if gross_win > 0 else None)
        )

        if len(rs) > 1:
            stdev = statistics.pstdev(rs)
            # A Sharpe-LIKE statistic on per-trade R, not an annualised Sharpe.
            # Naming it honestly matters: the two are not comparable.
            metrics.sharpe_like = (
                round(statistics.fmean(rs) / stdev, 4) if stdev > 0 else None
            )

    holding = [
        float(t["holding_days"]) for t in closed if t.get("holding_days") is not None
    ]
    if not holding:
        holding = [
            _days_between(t.get("opened_at"), t.get("closed_at"))
            for t in closed
            if t.get("opened_at") and t.get("closed_at")
        ]
        holding = [h for h in holding if h is not None]
    if holding:
        metrics.avg_holding_days = round(statistics.fmean(holding), 3)

    metrics.max_drawdown = _max_drawdown([float(p) for p in pnls])
    return metrics


def _days_between(start: Any, end: Any) -> float | None:
    from datetime import datetime

    try:
        s = datetime.fromisoformat(str(start))
        e = datetime.fromisoformat(str(end))
    except (TypeError, ValueError):
        return None
    return round((e - s).total_seconds() / 86400.0, 3)


def _max_drawdown(pnls: list[float]) -> float | None:
    """Largest peak-to-trough decline of the cumulative P&L curve."""
    if not pnls:
        return None
    cumulative = 0.0
    peak = 0.0
    worst = 0.0
    for pnl in pnls:
        cumulative += pnl
        peak = max(peak, cumulative)
        worst = min(worst, cumulative - peak)
    return round(worst, 4)


def equity_curve(trades: list[dict[str, Any]], starting_equity: float = 0.0) -> list[dict]:
    closed = sorted(
        (t for t in trades if t.get("closed_at") and t.get("realized_pnl") is not None),
        key=lambda t: str(t["closed_at"]),
    )
    equity = starting_equity
    out = []
    for trade in closed:
        equity += float(trade["realized_pnl"])
        out.append(
            {
                "at": trade["closed_at"],
                "equity": round(equity, 4),
                "ticker": trade["ticker"],
                "strategy": trade["strategy_id"],
                "r_multiple": trade.get("r_multiple"),
            }
        )
    return out


def sortino_like(rs: list[float]) -> float | None:
    """Downside-deviation variant. Reported alongside sharpe_like because a
    strategy with fat right tails is penalised unfairly by plain volatility."""
    if len(rs) < 2:
        return None
    downside = [r for r in rs if r < 0]
    if not downside:
        return None
    dd = math.sqrt(statistics.fmean([r * r for r in downside]))
    return round(statistics.fmean(rs) / dd, 4) if dd > 0 else None
