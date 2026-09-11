"""Strategy base contract (spec sections 4, 17, 20, 66).

Two rules define this layer:

1. A strategy never places an order. It returns a :class:`StrategyProposal`
   describing a setup and its geometry. Whether that becomes an order is decided
   by the risk engine, which a strategy cannot reach.
2. A strategy never assigns its own score. It reports sub-factor fits on 0-1;
   the scoring layer applies the configured weights. That keeps weights in one
   place and makes strategies comparable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from trading_universe.domain.enums import StrategyKind
from trading_universe.domain.market import Candle, Quote, Stock
from trading_universe.domain.regime import RegimeSnapshot, SectorRegime
from trading_universe.domain.snapshots import (
    FundamentalSnapshot,
    PoliticalSnapshot,
    SentimentSnapshot,
    TechnicalSnapshot,
)


@dataclass(slots=True)
class StrategyContext:
    """Everything a strategy is allowed to see for one ticker."""

    ticker: str
    stock: Stock
    technical: TechnicalSnapshot
    fundamental: FundamentalSnapshot
    sentiment: SentimentSnapshot
    now: datetime
    quote: Quote | None = None
    candles: list[Candle] = field(default_factory=list)
    political: PoliticalSnapshot | None = None
    regime: RegimeSnapshot | None = None
    sector_regime: SectorRegime | None = None

    @property
    def price(self) -> float:
        """Latest tradable price: the live quote if we have one, else the close."""
        if self.quote is not None and self.quote.last > 0:
            return self.quote.last
        return self.technical.close


@dataclass(slots=True)
class StrategyProposal:
    """A setup a strategy believes is present, with its geometry."""

    strategy_id: str
    kind: StrategyKind
    ticker: str
    entry: float
    stop: float
    target: float
    invalidation: str

    # Sub-factor fits on 0-1. The scorer multiplies these by configured weights.
    technical_fit: float = 0.0
    sentiment_fit: float = 0.0
    fundamental_fit: float = 0.0
    political_fit: float | None = None

    evidence: dict[str, Any] = field(default_factory=dict)
    holding_period_days: tuple[int, int] = (2, 10)


@dataclass(slots=True)
class StrategyEvaluation:
    """The full result of running a strategy, including near misses.

    Rejected and near-miss evaluations are persisted deliberately: the spec wants
    to be able to ask later whether rejected 65-score setups outperformed
    accepted 70-score ones (section 21).
    """

    strategy_id: str
    ticker: str
    setup_present: bool
    proposal: StrategyProposal | None = None
    failed_checks: list[str] = field(default_factory=list)
    passed_checks: list[str] = field(default_factory=list)

    @property
    def near_miss(self) -> bool:
        return not self.setup_present and len(self.failed_checks) <= 2


class Strategy(ABC):
    """Base class for every strategy."""

    id: str = "base"
    label: str = "Base Strategy"
    kind: StrategyKind = StrategyKind.STANDARD

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config: dict[str, Any] = config or {}

    # -- configuration helpers ---------------------------------------------
    def cfg(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.config
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("enabled", True))

    @property
    def minimum_reward_risk(self) -> float:
        return float(self.cfg("reward_risk.minimum", 1.75))

    @property
    def holding_period(self) -> tuple[int, int]:
        window = self.cfg("holding_period_days", [2, 10]) or [2, 10]
        return int(window[0]), int(window[1])

    # -- the contract -------------------------------------------------------
    @abstractmethod
    def evaluate(self, ctx: StrategyContext) -> StrategyEvaluation:
        """Decide whether this strategy's setup is present for ``ctx``."""

    # -- shared geometry helpers -------------------------------------------
    def place_stop(self, ctx: StrategyContext, method: str | None = None) -> float | None:
        """Technical invalidation stop (spec section 2: technical stops first).

        Never a fixed percentage. The stop sits below the structure whose failure
        would mean the thesis is wrong, with a small ATR buffer so ordinary noise
        does not take us out.
        """
        tech = ctx.technical
        method = method or str(self.cfg("stop.method", "swing_low"))
        buffer_mult = float(self.cfg("stop.atr_buffer_mult", 0.5))
        atr = tech.atr14 or 0.0
        buffer = atr * buffer_mult
        price = ctx.price

        level: float | None = None
        if method == "swing_low":
            lookback = int(self.cfg("stop.lookback_bars", 10))
            level = self._lowest_low(ctx, lookback)
        elif method == "ema20_atr":
            level = (tech.ema20 or price) - atr
        elif method == "structure":
            level = self._structure_level(ctx)

        if level is None or level <= 0:
            # Last resort: an ATR-derived invalidation. Still technical, but we
            # record that no structural level was available.
            level = price - max(atr * 1.5, price * 0.01)

        stop = level - buffer
        # A stop must actually be below the price, and not so far below that the
        # position is really a different trade.
        if stop >= price:
            stop = price - max(atr, price * 0.005)
        max_distance = price * float(self.cfg("stop.max_distance_pct", 0.12))
        if price - stop > max_distance:
            return None
        return round(stop, 4)

    def _lowest_low(self, ctx: StrategyContext, lookback: int) -> float | None:
        if not ctx.candles:
            return ctx.technical.swing_low
        window = ctx.candles[-lookback:]
        return min(c.low for c in window) if window else None

    def _structure_level(self, ctx: StrategyContext) -> float | None:
        """Consolidation floor / breakout base."""
        lookback = int(
            self.cfg("stop.consolidation_lookback", self.cfg("stop.lookback_bars", 15))
        )
        low = self._lowest_low(ctx, lookback)
        pct_buffer = float(
            self.cfg(
                "stop.below_breakout_buffer_pct",
                self.cfg("stop.below_reclaim_buffer_pct", 0.0),
            )
        )
        if low is None:
            return None
        return low * (1.0 - pct_buffer / 100.0)

    def build_target(
        self, entry: float, stop: float, resistance: float | None = None
    ) -> tuple[float, dict[str, Any]]:
        """Minimum target, extended when structure genuinely supports more.

        The minimum is a floor, never a fixed objective (spec section 2): if the
        next resistance sits at 2.6R we take 2.5R rather than settling for 1.75R.
        """
        from trading_universe.config import get_config

        risk = entry - stop
        min_rr = self.minimum_reward_risk
        minimum = entry + risk * min_rr
        notes: dict[str, Any] = {"minimum_target": round(minimum, 4), "minimum_rr": min_rr}

        rungs = get_config().strategies.get("targets.extension_rungs", []) or []
        chosen = minimum
        chosen_rr = min_rr
        if resistance and resistance > minimum:
            for rung in sorted(float(r) for r in rungs):
                candidate = entry + risk * rung
                if candidate <= resistance:
                    chosen, chosen_rr = candidate, rung
            notes["resistance"] = round(resistance, 4)
        elif resistance and resistance < minimum:
            # Honest about the tension rather than hiding it: the minimum R:R is
            # still enforced, but the path there runs through known supply.
            notes["resistance"] = round(resistance, 4)
            notes["resistance_below_minimum_target"] = True

        notes["selected_rr"] = chosen_rr
        return round(chosen, 4), notes

    def resistance_for(self, ctx: StrategyContext) -> float | None:
        """Nearest overhead supply: prior swing high, 20-day high or upper band."""
        tech = ctx.technical
        price = ctx.price
        candidates = [
            level
            for level in (tech.swing_high, tech.high_20, tech.bb_upper, tech.high_52w)
            if level and level > price * 1.005
        ]
        return min(candidates) if candidates else None

    # -- shared condition helpers ------------------------------------------
    def check_fundamentals(
        self, ctx: StrategyContext, key: str = "fundamentals"
    ) -> tuple[bool, list[str], list[str], float]:
        """Common fundamental gate. Returns (ok, passed, failed, fit 0-1)."""
        fund = ctx.fundamental
        passed: list[str] = []
        failed: list[str] = []

        min_quality = float(self.cfg(f"{key}.min_quality_score", 0.0))
        if fund.quality_score >= min_quality:
            passed.append(f"fundamental quality {fund.quality_score:.0f} >= {min_quality:.0f}")
        else:
            failed.append(f"fundamental quality {fund.quality_score:.0f} < {min_quality:.0f}")

        if self.cfg(f"{key}.require_revenue_growth_positive", False):
            if (fund.revenue_yoy or 0.0) > 0:
                passed.append(f"revenue YoY {(fund.revenue_yoy or 0):+.1%}")
            else:
                failed.append(f"revenue YoY {(fund.revenue_yoy or 0):+.1%} not positive")

        if self.cfg(f"{key}.require_fcf_positive", False):
            if fund.free_cash_flow_positive:
                passed.append("free cash flow positive")
            else:
                failed.append("free cash flow not positive")

        if self.cfg(f"{key}.require_margin_not_deteriorating", False):
            change = fund.operating_margin_change
            if change is None or change >= -0.005:
                passed.append("operating margin stable or improving")
            else:
                failed.append(f"operating margin deteriorating ({change:+.2%})")

        if self.cfg(f"{key}.reject_on_deteriorating_leverage", False):
            if fund.debt_trend == "deteriorating":
                failed.append("leverage deteriorating")
            else:
                passed.append(f"leverage {fund.debt_trend or 'unknown'}")

        if self.cfg(f"{key}.reject_on_negative_revenue_growth", False) and (
            fund.revenue_yoy is not None and fund.revenue_yoy < 0
        ):
            failed.append(f"revenue contracting ({fund.revenue_yoy:+.1%})")

        min_value_pct = self.cfg(f"{key}.min_value_percentile")
        if min_value_pct is not None:
            if fund.value_percentile is None:
                failed.append("value percentile unavailable")
            elif fund.value_percentile >= float(min_value_pct):
                passed.append(f"value percentile {fund.value_percentile:.0f}")
            else:
                failed.append(
                    f"value percentile {fund.value_percentile:.0f} < {float(min_value_pct):.0f}"
                )

        fit = max(0.0, min(1.0, fund.quality_score / 100.0))
        return (not failed), passed, failed, fit

    def check_sentiment(
        self, ctx: StrategyContext, key: str = "sentiment"
    ) -> tuple[bool, list[str], list[str], float]:
        s = ctx.sentiment
        passed: list[str] = []
        failed: list[str] = []

        min_7d = self.cfg(f"{key}.minimum_7d_score")
        if min_7d is not None:
            if s.score_7d >= float(min_7d):
                passed.append(f"7-day sentiment {s.score_7d:+.2f}")
            else:
                failed.append(f"7-day sentiment {s.score_7d:+.2f} < {float(min_7d):+.2f}")

        min_24h = self.cfg(f"{key}.minimum_24h_score")
        if min_24h is not None:
            if s.score_24h >= float(min_24h):
                passed.append(f"24-hour sentiment {s.score_24h:+.2f}")
            else:
                failed.append(f"24-hour sentiment {s.score_24h:+.2f} < {float(min_24h):+.2f}")

        if self.cfg(f"{key}.require_not_deteriorating", False):
            if s.deteriorating:
                failed.append("news sentiment still deteriorating")
            else:
                passed.append(f"news sentiment {s.trend}")

        max_neg = self.cfg(f"{key}.max_negative_7d")
        if max_neg is not None and s.score_7d < float(max_neg):
            failed.append(f"sentiment {s.score_7d:+.2f} below capitulation floor {max_neg}")

        min_improvement = self.cfg(f"{key}.min_7d_improvement")
        if min_improvement is not None:
            improvement = s.score_24h - s.score_7d
            if improvement >= float(min_improvement):
                passed.append(f"sentiment improving by {improvement:+.2f}")
            else:
                failed.append(
                    f"sentiment improvement {improvement:+.2f} < {float(min_improvement):+.2f}"
                )

        severe = self.cfg(f"{key}.severe_negative_threshold")
        if self.cfg(f"{key}.reject_severe_negative_catalyst", False) and severe is not None:
            if s.score_24h < float(severe):
                failed.append(f"severe negative catalyst ({s.score_24h:+.2f})")
            else:
                passed.append("no severe negative catalyst")

        # Fit maps [-1, 1] onto [0, 1], with a bonus for an improving trend.
        fit = (s.score_7d + 1.0) / 2.0
        if s.improving:
            fit = min(1.0, fit + 0.08)
        elif s.deteriorating:
            fit = max(0.0, fit - 0.08)
        # A ticker with no coverage at all is neutral, not good.
        if s.headline_count_7d == 0:
            fit = min(fit, 0.5)
        return (not failed), passed, failed, round(fit, 4)

    def regime_match(self, ctx: StrategyContext) -> float:
        """How well this strategy fits the prevailing regime, 0-1."""
        from trading_universe.config import get_config

        if ctx.regime is None:
            return 0.5
        preferred = get_config().strategies.regime_preferences(ctx.regime.regime.value)
        if not preferred:
            return 0.15  # e.g. RISK_OFF prefers nothing: be extremely selective
        if self.id == preferred[0]:
            return 1.0
        if self.id in preferred:
            return 0.8
        return 0.35

    def _fail(self, ctx: StrategyContext, failed: list[str], passed: list[str]) -> StrategyEvaluation:
        return StrategyEvaluation(
            strategy_id=self.id,
            ticker=ctx.ticker,
            setup_present=False,
            failed_checks=failed,
            passed_checks=passed,
        )
