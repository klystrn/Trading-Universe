"""The risk engine (spec sections 18, 19, 20, 30, 76).

This is the only path from a Signal to an Order. It is independent of strategy
logic so that no individual strategy can bypass a global constraint, and every
rejection is a machine-readable reason the UI can explain rather than a silent
drop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from trading_universe.config import ConfigStore, get_config
from trading_universe.data.freshness import FreshnessService
from trading_universe.domain.enums import (
    FreshnessStatus,
    OperatingMode,
    OrderSide,
    RejectionReason,
    Session,
)
from trading_universe.domain.market import Quote
from trading_universe.domain.portfolio import Order, Portfolio
from trading_universe.domain.signals import ExecutionDecision, Signal
from trading_universe.domain.snapshots import TechnicalSnapshot
from trading_universe.execution.sizing import size_position


@dataclass(slots=True)
class RiskContext:
    """Global state the risk engine needs. Assembled by the execution engine."""

    portfolio: Portfolio
    session: Session
    now: datetime
    operating_mode: OperatingMode = OperatingMode.ADVISORY
    open_orders: list[Order] = field(default_factory=list)
    recent_orders: list[Order] = field(default_factory=list)
    trades_opened_today: int = 0
    consecutive_losses: int = 0
    active_strategy: str | None = None
    quote: Quote | None = None
    technical: TechnicalSnapshot | None = None
    # True when the user has explicitly armed automatic execution in the UI.
    auto_trade_armed: bool = False


class RiskEngine:
    """Validates signals against every global constraint."""

    def __init__(
        self,
        config: ConfigStore | None = None,
        freshness: FreshnessService | None = None,
    ) -> None:
        self._config = config
        self.freshness = freshness

    @property
    def config(self) -> ConfigStore:
        return self._config or get_config()

    # -- main entry point ----------------------------------------------------
    def validate(self, signal: Signal, ctx: RiskContext) -> ExecutionDecision:
        """Return the decision for ``signal``. Never raises for a bad signal."""
        risk = self.config.risk
        reasons: list[RejectionReason] = []
        notes: list[str] = []

        # --- 1. kill switch -------------------------------------------------
        if risk.kill_switch_engaged:
            return ExecutionDecision(
                allowed=False,
                reasons=[RejectionReason.KILL_SWITCH_ENGAGED],
                notes=["the kill switch is engaged; all trading is stopped"],
            )

        # --- 2. direction ---------------------------------------------------
        if risk.long_only and signal.direction is not OrderSide.BUY:
            reasons.append(RejectionReason.SHORT_NOT_ALLOWED)
            notes.append("the platform is long-only")

        # --- 3. strategy gates ----------------------------------------------
        strategy_cfg = self.config.strategies.strategy(signal.strategy_id)
        if not strategy_cfg.get("enabled", True):
            reasons.append(RejectionReason.STRATEGY_DISABLED)
            notes.append(f"{signal.strategy_id} is disabled in configuration")

        # Only the active strategy may execute automatically. Other strategies
        # keep scanning and keep appearing in the scanner and universe; they just
        # cannot fire an order (spec 67).
        if (
            ctx.active_strategy is not None
            and signal.strategy_id != ctx.active_strategy
        ):
            reasons.append(RejectionReason.STRATEGY_NOT_ACTIVE)
            notes.append(
                f"{signal.strategy_id} is scanning but {ctx.active_strategy} is the "
                "active execution strategy"
            )

        # --- 4. score threshold ---------------------------------------------
        minimum = self.config.strategies.minimum_score(signal.strategy_id)
        if signal.score.total < minimum:
            reasons.append(RejectionReason.SCORE_BELOW_THRESHOLD)
            notes.append(f"score {signal.score.total:.0f} below the {minimum:.0f} threshold")

        # --- 5. geometry ------------------------------------------------------
        if signal.trade.stop >= signal.trade.entry:
            reasons.append(RejectionReason.INVALID_STOP)
            notes.append("stop is not below entry")
        min_rr = float(strategy_cfg.get("reward_risk", {}).get(
            "minimum", risk.minimum_reward_risk
        ))
        if signal.trade.reward_risk < min_rr - 1e-9:
            reasons.append(RejectionReason.REWARD_RISK_BELOW_MINIMUM)
            notes.append(
                f"reward:risk {signal.trade.reward_risk:.2f} below the {min_rr:.2f} minimum"
            )

        # --- 6. freshness -----------------------------------------------------
        reasons += self._check_freshness(signal, ctx, notes)

        # --- 7. session --------------------------------------------------------
        allowed_sessions = risk.get("sessions.allow_auto_execution_in", ["REGULAR"]) or []
        if ctx.session.value not in allowed_sessions:
            reasons.append(RejectionReason.SESSION_NOT_PERMITTED)
            notes.append(
                f"automatic execution is not permitted during {ctx.session.value}"
            )

        # --- 8. loss-streak guard ----------------------------------------------
        guard = risk.get("loss_streak_guard", {}) or {}
        if guard.get("enabled", False):
            limit = int(guard.get("consecutive_losses", 2))
            if ctx.consecutive_losses >= limit:
                reasons.append(RejectionReason.LOSS_STREAK_PAUSE)
                notes.append(
                    f"{ctx.consecutive_losses} consecutive losses; new entries are "
                    "paused for the session"
                )

        # --- 9. capacity --------------------------------------------------------
        if len(ctx.portfolio.positions) >= risk.max_open_positions:
            reasons.append(RejectionReason.MAX_OPEN_POSITIONS_REACHED)
            notes.append(
                f"{len(ctx.portfolio.positions)}/{risk.max_open_positions} positions open"
            )
        if ctx.trades_opened_today >= risk.max_new_trades_per_day:
            reasons.append(RejectionReason.MAX_NEW_TRADES_PER_DAY_REACHED)
            notes.append(
                f"{ctx.trades_opened_today}/{risk.max_new_trades_per_day} new trades today"
            )

        # --- 10. duplicates -------------------------------------------------------
        held = {p.ticker.upper() for p in ctx.portfolio.positions}
        if signal.ticker.upper() in held:
            if not risk.get("allow_duplicate_ticker", False):
                reasons.append(RejectionReason.DUPLICATE_TICKER_POSITION)
                notes.append(f"already holding {signal.ticker}")
            if not risk.get("allow_averaging_down", False):
                existing = next(
                    p for p in ctx.portfolio.positions if p.ticker.upper() == signal.ticker.upper()
                )
                if signal.trade.entry < existing.avg_entry:
                    reasons.append(RejectionReason.AVERAGING_DOWN_BLOCKED)
                    notes.append(
                        f"entry {signal.trade.entry:.2f} is below the existing average "
                        f"{existing.avg_entry:.2f}"
                    )

        if self._is_duplicate_order(signal, ctx):
            reasons.append(RejectionReason.DUPLICATE_ORDER)
            notes.append("an equivalent order was submitted within the duplicate window")

        # --- 11. liquidity and spread ---------------------------------------------
        reasons += self._check_liquidity(signal, ctx, notes)

        # --- 12. entry drift --------------------------------------------------------
        max_drift = float(risk.get("orders.max_entry_drift_pct", 0.01))
        if ctx.quote is not None and signal.trade.entry > 0:
            drift = abs(ctx.quote.last - signal.trade.entry) / signal.trade.entry
            if drift > max_drift:
                reasons.append(RejectionReason.ENTRY_DRIFTED)
                notes.append(
                    f"price moved {drift:.2%} from the analysed entry "
                    f"(limit {max_drift:.2%}) - this is no longer the trade we scored"
                )

        # --- 13. sizing ---------------------------------------------------------------
        sizing = size_position(
            entry=signal.trade.entry,
            stop=signal.trade.stop,
            max_position_value=min(signal.trade.max_position_value, risk.max_position_value),
            allow_fractional=risk.allow_fractional_shares,
            min_notional=float(risk.get("orders.min_notional", 5.0)),
        )
        if not sizing.viable or sizing.position_value < float(
            risk.get("orders.min_notional", 5.0)
        ):
            reasons.append(RejectionReason.POSITION_VALUE_TOO_SMALL)
            notes.append(sizing.note or "position could not be sized")
        elif sizing.note:
            notes.append(sizing.note)

        # --- 14. live-order interlocks ------------------------------------------------
        if ctx.operating_mode is OperatingMode.LIVE_AUTO:
            from trading_universe.settings import get_settings

            settings = get_settings()
            if not settings.real_orders_permitted:
                reasons.append(RejectionReason.REAL_ORDERS_NOT_ENABLED)
                notes.append(
                    "LIVE_AUTO requires TRADING_ENV=REAL and ALLOW_REAL_ORDERS=true"
                )
            if not ctx.auto_trade_armed:
                reasons.append(RejectionReason.REAL_ORDERS_NOT_ENABLED)
                notes.append("automatic execution has not been armed in the UI")

        # --- verdict --------------------------------------------------------------------
        unique_reasons = list(dict.fromkeys(reasons))
        if unique_reasons:
            return ExecutionDecision(allowed=False, reasons=unique_reasons, notes=notes)

        notes.append(
            f"{sizing.quantity:g} shares at {signal.trade.entry:.2f} "
            f"= ${sizing.position_value:,.2f} deployed, ${sizing.risk_amount:,.2f} at risk"
        )
        return ExecutionDecision(
            allowed=True,
            reasons=[],
            notes=notes,
            quantity=sizing.quantity,
            position_value=sizing.position_value,
        )

    # -- individual checks ----------------------------------------------------
    def _check_freshness(
        self, signal: Signal, ctx: RiskContext, notes: list[str]
    ) -> list[RejectionReason]:
        risk = self.config.risk
        if not risk.get("require_fresh_market_data", True):
            return []
        if self.freshness is None:
            notes.append("freshness service unavailable - treating market data as stale")
            return [RejectionReason.MARKET_DATA_STALE]

        ok, blockers, _ = self.freshness.evaluate_strategy(signal.strategy_id, ctx.now)
        if ok:
            return []

        reasons: list[RejectionReason] = []
        for source in blockers:
            state = self.freshness.state(source, ctx.now)
            age = f"{state.age_seconds:.0f}s" if state.age_seconds is not None else "never"
            notes.append(f"{source} is {state.status.value} (age {age})")
            if source.startswith("news"):
                reasons.append(RejectionReason.NEWS_DATA_STALE)
            elif source.startswith(("quote", "candle")):
                reasons.append(RejectionReason.MARKET_DATA_STALE)
            else:
                reasons.append(RejectionReason.REQUIRED_SOURCE_UNAVAILABLE)
        return reasons

    def _check_liquidity(
        self, signal: Signal, ctx: RiskContext, notes: list[str]
    ) -> list[RejectionReason]:
        cfg = self.config.risk.get("liquidity", {}) or {}
        reasons: list[RejectionReason] = []

        price = ctx.quote.last if ctx.quote else signal.trade.entry
        min_price = float(cfg.get("min_price", 0.0))
        if price < min_price:
            reasons.append(RejectionReason.PRICE_BELOW_MINIMUM)
            notes.append(f"price ${price:.2f} below the ${min_price:.2f} minimum")

        tech = ctx.technical
        if tech is not None:
            min_dollar = float(cfg.get("min_avg_dollar_volume_20d", 0.0))
            if tech.avg_dollar_volume_20 and tech.avg_dollar_volume_20 < min_dollar:
                reasons.append(RejectionReason.INSUFFICIENT_LIQUIDITY)
                notes.append(
                    f"20-day dollar volume ${tech.avg_dollar_volume_20:,.0f} below "
                    f"${min_dollar:,.0f}"
                )
            min_shares = float(cfg.get("min_avg_share_volume_20d", 0.0))
            if tech.avg_volume_20 and tech.avg_volume_20 < min_shares:
                reasons.append(RejectionReason.INSUFFICIENT_LIQUIDITY)
                notes.append(
                    f"20-day share volume {tech.avg_volume_20:,.0f} below {min_shares:,.0f}"
                )

        if ctx.quote is not None:
            spread = ctx.quote.spread_pct
            max_spread = float(cfg.get("max_spread_pct", 1.0))
            if spread is not None and spread > max_spread:
                reasons.append(RejectionReason.SPREAD_TOO_WIDE)
                notes.append(f"spread {spread:.3%} wider than the {max_spread:.3%} limit")

        return reasons

    def _is_duplicate_order(self, signal: Signal, ctx: RiskContext) -> bool:
        window = float(self.config.risk.get("orders.duplicate_window_seconds", 300))
        cutoff = ctx.now - timedelta(seconds=window)
        candidates = list(ctx.open_orders) + list(ctx.recent_orders)
        for order in candidates:
            if order.ticker.upper() != signal.ticker.upper():
                continue
            if order.side is not signal.direction:
                continue
            created = order.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if created >= cutoff:
                return True
        return False

    # -- explanation helper ---------------------------------------------------
    @staticmethod
    def explain(decision: ExecutionDecision) -> str:
        if decision.allowed:
            return "Executable. " + " ".join(decision.notes)
        joined = ", ".join(r.value for r in decision.reasons)
        return f"Blocked ({joined}). " + " ".join(decision.notes)


def check_freshness_status(status: FreshnessStatus) -> bool:
    """A source in this status may be traded on."""
    return status in (FreshnessStatus.LIVE, FreshnessStatus.HEALTHY, FreshnessStatus.DEGRADED)
