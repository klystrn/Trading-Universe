"""The risk engine is the only path from a Signal to an Order (spec 18, 76).

These tests are the safety net for that claim: each one removes a single
permission and asserts the engine refuses, with the right machine-readable
reason.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from trading_universe.domain.enums import (
    OperatingMode,
    OrderSide,
    OrderStatus,
    OrderType,
    RejectionReason,
    Session,
)
from trading_universe.domain.portfolio import Order, Position
from trading_universe.execution.risk_engine import RiskEngine


@pytest.fixture
def engine(config, freshness):
    return RiskEngine(config, freshness)


def _validate(engine, signal, ctx, technical, quote):
    ctx.technical = technical
    ctx.quote = quote
    return engine.validate(signal, ctx)


class TestHappyPath:
    def test_a_clean_signal_is_executable(
        self, engine, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert decision.allowed, decision.notes
        assert decision.quantity == 1.5           # $150 / $100
        assert decision.position_value == 150.0
        assert decision.reasons == []


class TestKillSwitch:
    def test_kill_switch_blocks_everything(
        self, engine, config, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        config.risk.set("kill_switch_engaged", True)
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert not decision.allowed
        assert decision.reasons == [RejectionReason.KILL_SWITCH_ENGAGED]

    def test_kill_switch_short_circuits_other_checks(
        self, engine, config, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        """Nothing else needs evaluating once trading is stopped."""
        config.risk.set("kill_switch_engaged", True)
        config.risk.set("max_open_positions", 0)
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert decision.reasons == [RejectionReason.KILL_SWITCH_ENGAGED]


class TestScoreAndGeometry:
    def test_score_below_threshold_is_rejected(
        self, engine, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        sample_signal.score.technical = 10.0     # total falls to 59
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.SCORE_BELOW_THRESHOLD in decision.reasons

    def test_reward_risk_below_minimum_is_rejected(
        self, engine, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        from trading_universe.domain.signals import TradeParams

        # 1.5R, below the 1.75 floor.
        sample_signal.trade = TradeParams(entry=100.0, stop=96.0, target=106.0)
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.REWARD_RISK_BELOW_MINIMUM in decision.reasons

    def test_exactly_the_minimum_reward_risk_passes(
        self, engine, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        """1.75 must not be rejected by a floating-point hair."""
        from trading_universe.domain.signals import TradeParams

        sample_signal.trade = TradeParams(entry=100.0, stop=96.0, target=107.0)
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.REWARD_RISK_BELOW_MINIMUM not in decision.reasons


class TestCapacity:
    def test_max_open_positions(
        self, engine, config, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        risk_context.portfolio.positions = [
            Position(ticker=f"T{i}", quantity=1, avg_entry=10, current_price=10)
            for i in range(config.risk.max_open_positions)
        ]
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.MAX_OPEN_POSITIONS_REACHED in decision.reasons

    def test_max_new_trades_per_day(
        self, engine, config, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        risk_context.trades_opened_today = config.risk.max_new_trades_per_day
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.MAX_NEW_TRADES_PER_DAY_REACHED in decision.reasons

    def test_duplicate_ticker_position(
        self, engine, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        risk_context.portfolio.positions = [
            Position(ticker="AAPL", quantity=1, avg_entry=90.0, current_price=100.0)
        ]
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.DUPLICATE_TICKER_POSITION in decision.reasons

    def test_averaging_down_is_blocked(
        self, engine, config, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        config.risk.set("allow_duplicate_ticker", True)
        risk_context.portfolio.positions = [
            Position(ticker="AAPL", quantity=1, avg_entry=120.0, current_price=100.0)
        ]
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.AVERAGING_DOWN_BLOCKED in decision.reasons

    def test_duplicate_order_inside_the_window(
        self, engine, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        risk_context.recent_orders = [
            Order(
                ticker="AAPL", side=OrderSide.BUY, order_type=OrderType.LIMIT,
                quantity=1.0, limit_price=100.0, status=OrderStatus.SUBMITTED,
                created_at=datetime.now(UTC) - timedelta(seconds=10),
            )
        ]
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.DUPLICATE_ORDER in decision.reasons

    def test_an_old_order_is_not_a_duplicate(
        self, engine, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        risk_context.recent_orders = [
            Order(
                ticker="AAPL", side=OrderSide.BUY, order_type=OrderType.LIMIT,
                quantity=1.0, limit_price=100.0, status=OrderStatus.FILLED,
                created_at=datetime.now(UTC) - timedelta(hours=2),
            )
        ]
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.DUPLICATE_ORDER not in decision.reasons


class TestFreshness:
    def test_stale_market_data_blocks_execution(
        self, engine, freshness, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        """Spec 30: a stale value must never masquerade as live."""
        freshness.record(
            "quote_active_candidate",
            event_time=datetime.now(UTC) - timedelta(minutes=10),
        )
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.MARKET_DATA_STALE in decision.reasons

    def test_degraded_news_blocks_only_news_dependent_strategies(
        self, engine, freshness, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        """Spec 30's worked example: Momentum Pullback may trade while
        Catalyst Breakout is disabled by a degraded news feed."""
        freshness.mark_unavailable("news_discovery", "GDELT unreachable")
        freshness.mark_unavailable("news_sentiment_aggregate", "no articles")

        momentum = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert momentum.allowed, momentum.notes

        sample_signal.strategy_id = "fundamental_catalyst_breakout"
        catalyst = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert not catalyst.allowed
        assert RejectionReason.NEWS_DATA_STALE in catalyst.reasons

    def test_missing_freshness_service_is_treated_as_stale(
        self, config, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        engine = RiskEngine(config, freshness=None)
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.MARKET_DATA_STALE in decision.reasons


class TestLiquidity:
    def test_thin_dollar_volume_is_rejected(
        self, engine, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        liquid_technical.avg_dollar_volume_20 = 100_000.0
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.INSUFFICIENT_LIQUIDITY in decision.reasons

    def test_wide_spread_is_rejected(
        self, engine, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        tight_quote.bid = 98.0
        tight_quote.ask = 102.0
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.SPREAD_TOO_WIDE in decision.reasons

    def test_entry_drift_abandons_a_stale_setup(
        self, engine, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        tight_quote.last = 104.0      # 4% away from the analysed entry
        tight_quote.bid, tight_quote.ask = 103.99, 104.01
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.ENTRY_DRIFTED in decision.reasons


class TestSessionAndStreak:
    def test_execution_outside_the_regular_session_is_blocked(
        self, engine, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        risk_context.session = Session.AFTER_HOURS
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.SESSION_NOT_PERMITTED in decision.reasons

    def test_loss_streak_pauses_new_entries(
        self, engine, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        risk_context.consecutive_losses = 2
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.LOSS_STREAK_PAUSE in decision.reasons

    def test_loss_streak_guard_is_configurable_not_hardcoded(
        self, engine, config, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        config.risk.set("loss_streak_guard.enabled", False)
        risk_context.consecutive_losses = 5
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.LOSS_STREAK_PAUSE not in decision.reasons


class TestStrategyGating:
    def test_only_the_active_strategy_may_execute(
        self, engine, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        """Spec 67: other strategies keep scanning but cannot fire an order."""
        risk_context.active_strategy = "quality_volatility_squeeze"
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.STRATEGY_NOT_ACTIVE in decision.reasons

    def test_the_active_strategy_passes(
        self, engine, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        risk_context.active_strategy = "quality_momentum_pullback"
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert decision.allowed, decision.notes

    def test_a_disabled_strategy_is_rejected(
        self, engine, config, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        config.strategies.set("strategies.quality_momentum_pullback.enabled", False)
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.STRATEGY_DISABLED in decision.reasons

    def test_shorts_are_rejected_while_long_only(
        self, engine, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        sample_signal.direction = OrderSide.SELL
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.SHORT_NOT_ALLOWED in decision.reasons


class TestLiveInterlocks:
    def test_live_auto_without_environment_permission_is_blocked(
        self, engine, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        risk_context.operating_mode = OperatingMode.LIVE_AUTO
        risk_context.auto_trade_armed = True
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.REAL_ORDERS_NOT_ENABLED in decision.reasons

    def test_live_auto_without_ui_arming_is_blocked(
        self, engine, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        risk_context.operating_mode = OperatingMode.LIVE_AUTO
        risk_context.auto_trade_armed = False
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.REAL_ORDERS_NOT_ENABLED in decision.reasons


class TestReporting:
    def test_every_rejection_carries_a_machine_readable_reason(
        self, engine, config, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        """Spec 76: the UI explains rejections, it does not drop them silently."""
        config.risk.set("max_open_positions", 0)
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert not decision.allowed
        assert decision.reasons
        assert all(isinstance(r, RejectionReason) for r in decision.reasons)
        assert decision.notes
        assert "Blocked" in RiskEngine.explain(decision)

    def test_multiple_reasons_are_all_reported(
        self, engine, config, sample_signal, risk_context, liquid_technical, tight_quote
    ):
        config.risk.set("max_open_positions", 0)
        risk_context.session = Session.CLOSED
        decision = _validate(engine, sample_signal, risk_context, liquid_technical, tight_quote)
        assert RejectionReason.MAX_OPEN_POSITIONS_REACHED in decision.reasons
        assert RejectionReason.SESSION_NOT_PERMITTED in decision.reasons
