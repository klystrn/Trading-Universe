"""Execution engine: the single seam between a scored Signal and a broker order.

Responsibilities:

* assemble the :class:`RiskContext` from live portfolio and session state
* ask the :class:`RiskEngine` for a verdict - and honour it
* in ADVISORY mode, stop there and record the recommendation
* in PAPER_AUTO / LIVE_AUTO, place the order and attach stop/target
* persist a :class:`TradeThesis` for accepted AND rejected signals
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from trading_universe.config import get_config
from trading_universe.domain.enums import (
    ExecutionSource,
    OperatingMode,
    OrderSide,
    OrderType,
    Session,
)
from trading_universe.domain.portfolio import Order
from trading_universe.domain.signals import ExecutionDecision, Signal
from trading_universe.domain.snapshots import TechnicalSnapshot
from trading_universe.domain.thesis import TradeThesis
from trading_universe.execution.broker_base import BrokerBase, BrokerError
from trading_universe.execution.risk_engine import RiskContext, RiskEngine
from trading_universe.services.sessions import current_session
from trading_universe.thesis.builder import build_thesis

logger = logging.getLogger(__name__)


class ExecutionEngine:
    def __init__(
        self,
        broker: BrokerBase,
        risk_engine: RiskEngine,
        operating_mode: OperatingMode = OperatingMode.ADVISORY,
    ) -> None:
        self.broker = broker
        self.risk = risk_engine
        self.operating_mode = operating_mode
        self.auto_trade_armed = False
        self.active_strategy: str | None = None
        self.rejected_today: int = 0
        self._theses: list[TradeThesis] = []

    # -- state ---------------------------------------------------------------
    def set_operating_mode(self, mode: OperatingMode) -> None:
        if mode is not OperatingMode.LIVE_AUTO:
            # Dropping out of live always disarms; re-arming must be deliberate.
            self.auto_trade_armed = False
        self.operating_mode = mode

    def arm_auto_trade(self, armed: bool) -> None:
        self.auto_trade_armed = armed

    def set_active_strategy(self, strategy_id: str | None) -> None:
        self.active_strategy = strategy_id

    @property
    def theses(self) -> list[TradeThesis]:
        return list(self._theses)

    # -- context -------------------------------------------------------------
    def build_context(
        self,
        technical: TechnicalSnapshot | None = None,
        quote=None,
        now: datetime | None = None,
        session: Session | None = None,
    ) -> RiskContext:
        now = now or datetime.now(UTC)
        portfolio = self.broker.get_portfolio()
        risk = get_config().risk
        portfolio.max_open_positions = risk.max_open_positions
        portfolio.max_new_trades_per_day = risk.max_new_trades_per_day

        trades_today = getattr(self.broker, "trades_opened_today", lambda: 0)()
        losses = getattr(self.broker, "consecutive_losses", lambda: 0)()
        portfolio.trades_opened_today = trades_today

        try:
            open_orders = self.broker.get_open_orders()
        except BrokerError as exc:
            logger.warning("could not read open orders: %s", exc)
            open_orders = []

        return RiskContext(
            portfolio=portfolio,
            session=session or current_session(now),
            now=now,
            operating_mode=self.operating_mode,
            open_orders=open_orders,
            recent_orders=getattr(self.broker, "get_orders", lambda: [])(),
            trades_opened_today=trades_today,
            consecutive_losses=losses,
            active_strategy=self.active_strategy,
            quote=quote,
            technical=technical,
            auto_trade_armed=self.auto_trade_armed,
        )

    # -- the main path --------------------------------------------------------
    def process(
        self,
        signal: Signal,
        ctx: RiskContext | None = None,
        execution_source: ExecutionSource = ExecutionSource.AUTO,
    ) -> tuple[ExecutionDecision, Order | None, TradeThesis]:
        """Validate and, where permitted, execute. Always returns a thesis."""
        ctx = ctx or self.build_context()
        decision = self.risk.validate(signal, ctx)
        signal.execution = decision

        thesis = build_thesis(signal, accepted=decision.allowed)
        self._theses.append(thesis)

        if not decision.allowed:
            self.rejected_today += 1
            logger.info(
                "signal %s %s rejected: %s",
                signal.ticker, signal.strategy_id,
                ", ".join(r.value for r in decision.reasons),
            )
            return decision, None, thesis

        # ADVISORY: recommend, do not execute. The decision still says
        # "executable" so the UI can show that only the mode is holding it back.
        if self.operating_mode is OperatingMode.ADVISORY:
            decision.notes.append(
                "ADVISORY mode: this qualifies but will not be executed automatically"
            )
            return decision, None, thesis

        order = self._build_order(signal, decision, execution_source)
        try:
            placed = self.broker.place_order(order)
        except BrokerError as exc:
            logger.error("order placement failed for %s: %s", signal.ticker, exc)
            decision.allowed = False
            decision.notes.append(f"broker error: {exc}")
            self.rejected_today += 1
            thesis.accepted = False
            return decision, None, thesis

        # Attach the technical stop and target so the position is managed even
        # if nothing else runs again today.
        setter = getattr(self.broker, "set_position_targets", None)
        if setter is not None and placed.status.value == "FILLED":
            setter(signal.ticker, signal.trade.stop, signal.trade.target)

        thesis.trade_id = placed.broker_order_id or placed.order_id
        return decision, placed, thesis

    def _build_order(
        self, signal: Signal, decision: ExecutionDecision, source: ExecutionSource
    ) -> Order:
        if self.operating_mode is OperatingMode.LIVE_AUTO:
            from trading_universe.execution.live import check_live_gates

            check_live_gates(self.operating_mode, self.auto_trade_armed).raise_if_blocked()

        return Order(
            ticker=signal.ticker,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=decision.quantity or 0.0,
            limit_price=signal.trade.entry,
            stop_price=signal.trade.stop,
            signal_id=signal.signal_id,
            strategy_id=signal.strategy_id,
            operating_mode=self.operating_mode,
            execution_source=source,
            paper=self.operating_mode is not OperatingMode.LIVE_AUTO,
            created_at=datetime.now(UTC),
        )

    # -- kill switch -----------------------------------------------------------
    def engage_kill_switch(self) -> None:
        get_config().risk.set_kill_switch(True)
        self.auto_trade_armed = False
        logger.warning("KILL SWITCH ENGAGED - all new entries stopped")

    def release_kill_switch(self) -> None:
        get_config().risk.set_kill_switch(False)
        logger.warning("kill switch released")
