"""Execution engine, paper broker and the live-trading interlocks."""

from __future__ import annotations

import pytest

from trading_universe.domain.enums import (
    OperatingMode,
    OrderSide,
    OrderStatus,
    OrderType,
    TradeResult,
)
from trading_universe.domain.portfolio import Order
from trading_universe.execution.broker_base import BrokerError
from trading_universe.execution.engine import ExecutionEngine
from trading_universe.execution.live import check_live_gates
from trading_universe.execution.risk_engine import RiskEngine


@pytest.fixture
def engine(paper_broker, config, freshness):
    return ExecutionEngine(
        paper_broker, RiskEngine(config, freshness), OperatingMode.PAPER_AUTO
    )


def _order(ticker="AAPL", qty=1.5, price=100.0, side=OrderSide.BUY):
    from datetime import UTC, datetime

    return Order(
        ticker=ticker, side=side, order_type=OrderType.LIMIT, quantity=qty,
        limit_price=price, stop_price=96.0, strategy_id="quality_momentum_pullback",
        created_at=datetime.now(UTC),
    )


class TestPaperBroker:
    def test_a_buy_fills_and_opens_a_position(self, paper_broker):
        filled = paper_broker.place_order(_order())
        assert filled.status is OrderStatus.FILLED
        assert filled.avg_fill_price == 100.0
        positions = paper_broker.get_positions()
        assert len(positions) == 1
        assert positions[0].ticker == "AAPL"
        assert positions[0].quantity == 1.5

    def test_cash_is_deducted(self, paper_broker):
        before = paper_broker.get_portfolio().cash
        paper_broker.place_order(_order(qty=1.0, price=100.0))
        assert paper_broker.get_portfolio().cash == pytest.approx(before - 100.0)

    def test_insufficient_cash_is_rejected(self, paper_broker):
        rejected = paper_broker.place_order(_order(qty=1000.0, price=100.0))
        assert rejected.status is OrderStatus.REJECTED
        assert "insufficient cash" in (rejected.rejection_reason or "")

    def test_a_duplicate_client_order_id_is_rejected(self, paper_broker):
        first = _order()
        paper_broker.place_order(first)
        duplicate = _order()
        duplicate.client_order_id = first.client_order_id
        assert paper_broker.place_order(duplicate).status is OrderStatus.REJECTED

    def test_a_stop_is_honoured_on_sync(self, paper_broker):
        paper_broker.place_order(_order())
        paper_broker.set_position_targets("AAPL", stop=96.0, target=107.0)
        paper_broker.sync({"AAPL": 95.0})
        assert paper_broker.get_positions() == []
        trade = paper_broker.get_trades()[0]
        assert trade.result is TradeResult.LOSS
        assert trade.exit_reason == "stop_loss"

    def test_a_target_is_honoured_on_sync(self, paper_broker):
        paper_broker.place_order(_order())
        paper_broker.set_position_targets("AAPL", stop=96.0, target=107.0)
        paper_broker.sync({"AAPL": 108.0})
        assert paper_broker.get_positions() == []
        trade = paper_broker.get_trades()[0]
        assert trade.result is TradeResult.WIN
        assert trade.r_multiple == pytest.approx(1.75, abs=0.01)

    def test_a_price_between_stop_and_target_holds_the_position(self, paper_broker):
        paper_broker.place_order(_order())
        paper_broker.set_position_targets("AAPL", stop=96.0, target=107.0)
        paper_broker.sync({"AAPL": 101.0})
        assert len(paper_broker.get_positions()) == 1

    def test_consecutive_losses_are_counted(self, paper_broker):
        for ticker in ("AAPL", "MSFT"):
            paper_broker.place_order(_order(ticker=ticker))
            paper_broker.set_position_targets(ticker, stop=96.0, target=107.0)
            paper_broker.sync({ticker: 95.0})
        assert paper_broker.consecutive_losses() == 2

    def test_a_win_resets_the_loss_streak(self, paper_broker):
        paper_broker.place_order(_order(ticker="AAPL"))
        paper_broker.set_position_targets("AAPL", stop=96.0, target=107.0)
        paper_broker.sync({"AAPL": 95.0})
        paper_broker.place_order(_order(ticker="MSFT"))
        paper_broker.set_position_targets("MSFT", stop=96.0, target=107.0)
        paper_broker.sync({"MSFT": 108.0})
        assert paper_broker.consecutive_losses() == 0


class TestExecutionEngine:
    def test_advisory_mode_never_places_an_order(
        self, paper_broker, config, freshness, sample_signal, liquid_technical, tight_quote
    ):
        """Spec 22.1: advisory recommends, it does not execute."""
        engine = ExecutionEngine(
            paper_broker, RiskEngine(config, freshness), OperatingMode.ADVISORY
        )
        ctx = engine.build_context(technical=liquid_technical, quote=tight_quote)
        decision, order, thesis = engine.process(sample_signal, ctx)

        assert decision.allowed          # it qualifies...
        assert order is None             # ...but nothing is sent
        assert paper_broker.get_positions() == []
        assert any("ADVISORY" in n for n in decision.notes)

    def test_paper_auto_places_an_order(
        self, engine, paper_broker, sample_signal, liquid_technical, tight_quote
    ):
        ctx = engine.build_context(technical=liquid_technical, quote=tight_quote)
        decision, order, thesis = engine.process(sample_signal, ctx)
        assert decision.allowed
        assert order is not None
        assert order.status is OrderStatus.FILLED
        assert order.paper is True
        assert len(paper_broker.get_positions()) == 1

    def test_a_rejected_signal_still_produces_a_thesis(
        self, engine, config, sample_signal, liquid_technical, tight_quote
    ):
        """Spec 21: rejected signals are recorded, not dropped."""
        config.risk.set("max_open_positions", 0)
        ctx = engine.build_context(technical=liquid_technical, quote=tight_quote)
        decision, order, thesis = engine.process(sample_signal, ctx)

        assert not decision.allowed
        assert order is None
        assert thesis is not None
        assert thesis.accepted is False
        assert thesis.rejection_reasons

    def test_the_thesis_captures_the_full_setup(
        self, engine, sample_signal, liquid_technical, tight_quote
    ):
        sample_signal.evidence = {
            "rsi14": 52.4, "volume_ratio": 1.37, "quality_score": 81.0,
            "sentiment_trend": "improving", "consensus_score": 0.4,
        }
        ctx = engine.build_context(technical=liquid_technical, quote=tight_quote)
        _, _, thesis = engine.process(sample_signal, ctx)

        assert thesis.entry == 100.0
        assert thesis.stop == 96.0
        assert thesis.reward_risk == 1.75
        assert thesis.technical["rsi14"] == 52.4
        assert thesis.fundamentals["quality_score"] == 81.0
        assert thesis.sentiment["sentiment_trend"] == "improving"
        assert thesis.political is not None
        assert thesis.invalidation

    def test_the_kill_switch_stops_execution(
        self, engine, paper_broker, sample_signal, liquid_technical, tight_quote
    ):
        engine.engage_kill_switch()
        ctx = engine.build_context(technical=liquid_technical, quote=tight_quote)
        decision, order, _ = engine.process(sample_signal, ctx)
        assert not decision.allowed
        assert order is None
        assert paper_broker.get_positions() == []
        engine.release_kill_switch()

    def test_capacity_is_enforced_across_a_batch(
        self, engine, config, paper_broker, liquid_technical, tight_quote
    ):
        """Repeated signals must not exceed max_new_trades_per_day."""
        from datetime import UTC, datetime

        from trading_universe.domain.signals import (
            Signal,
            SignalScore,
            TradeParams,
        )

        for ticker in ("AAPL", "MSFT", "NVDA", "AMD", "INTC"):
            signal = Signal(
                ticker=ticker,
                strategy_id="quality_momentum_pullback",
                generated_at=datetime.now(UTC),
                score=SignalScore(technical=32.0, sentiment=24.0, fundamental=25.0),
                trade=TradeParams(entry=100.0, stop=96.0, target=107.0),
            )
            technical = liquid_technical.model_copy(update={"ticker": ticker})
            quote = tight_quote.model_copy(update={"ticker": ticker})
            ctx = engine.build_context(technical=technical, quote=quote)
            engine.process(signal, ctx)

        assert len(paper_broker.get_positions()) <= config.risk.max_new_trades_per_day

    def test_switching_out_of_live_mode_disarms(self, engine):
        engine.arm_auto_trade(True)
        engine.set_operating_mode(OperatingMode.PAPER_AUTO)
        assert engine.auto_trade_armed is False


class TestLiveInterlocks:
    def test_all_four_gates_are_reported_when_blocked(self):
        """Spec 22.3: the live path is intentionally hard to enable."""
        gate = check_live_gates(OperatingMode.ADVISORY, ui_armed=False)
        assert not gate.permitted
        assert any("TRADING_ENV" in f for f in gate.failures)
        assert any("ALLOW_REAL_ORDERS" in f for f in gate.failures)
        assert any("LIVE_AUTO" in f for f in gate.failures)
        assert any("armed" in f for f in gate.failures)

    def test_environment_alone_is_not_enough(self, monkeypatch):
        from trading_universe.settings import reload_settings

        monkeypatch.setenv("TRADING_ENV", "REAL")
        monkeypatch.setenv("ALLOW_REAL_ORDERS", "true")
        reload_settings()
        try:
            gate = check_live_gates(OperatingMode.PAPER_AUTO, ui_armed=False)
            assert not gate.permitted
            assert any("LIVE_AUTO" in f for f in gate.failures)
        finally:
            monkeypatch.setenv("TRADING_ENV", "PAPER")
            monkeypatch.setenv("ALLOW_REAL_ORDERS", "false")
            reload_settings()

    def test_all_gates_together_permit(self, monkeypatch):
        from trading_universe.settings import reload_settings

        monkeypatch.setenv("TRADING_ENV", "REAL")
        monkeypatch.setenv("ALLOW_REAL_ORDERS", "true")
        reload_settings()
        try:
            gate = check_live_gates(OperatingMode.LIVE_AUTO, ui_armed=True)
            assert gate.permitted
            assert gate.failures == []
        finally:
            monkeypatch.setenv("TRADING_ENV", "PAPER")
            monkeypatch.setenv("ALLOW_REAL_ORDERS", "false")
            reload_settings()

    def test_a_blocked_gate_raises_rather_than_returning_quietly(self):
        gate = check_live_gates(OperatingMode.ADVISORY, ui_armed=False)
        with pytest.raises(BrokerError, match="live trading blocked"):
            gate.raise_if_blocked()

    def test_the_default_environment_is_safe(self):
        from trading_universe.settings import get_settings

        settings = get_settings()
        assert settings.trading_env == "PAPER"
        assert settings.allow_real_orders is False
        assert settings.real_orders_permitted is False
        assert settings.is_paper is True
