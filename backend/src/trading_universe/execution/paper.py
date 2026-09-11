"""Internal paper broker.

Simulates fills, positions and stop/target management with no external
dependency, so PAPER_AUTO works offline and tests are deterministic. When Moomoo
OpenD is available, :class:`MoomooBroker` in paper mode is the more faithful
choice; this one is the fallback and the test double.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from trading_universe.domain.enums import OrderSide, OrderStatus, OrderType, TradeResult
from trading_universe.domain.portfolio import Order, Portfolio, Position, Trade
from trading_universe.execution.broker_base import BrokerBase


class PaperBroker(BrokerBase):
    name = "paper"
    paper = True

    def __init__(self, starting_cash: float = 10_000.0, slippage_bps: float = 2.0) -> None:
        self._lock = threading.RLock()
        self.starting_cash = starting_cash
        self._cash = starting_cash
        self._slippage = slippage_bps / 10_000.0
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}
        self._trades: dict[str, Trade] = {}
        self._realized_total = 0.0
        self._realized_today = 0.0
        self._today = datetime.now(UTC).date()
        self._connected = False

    # -- lifecycle ----------------------------------------------------------
    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    # -- state --------------------------------------------------------------
    def get_portfolio(self) -> Portfolio:
        with self._lock:
            self._roll_day()
            return Portfolio(
                as_of=datetime.now(UTC),
                cash=round(self._cash, 4),
                buying_power=round(self._cash, 4),
                positions=list(self._positions.values()),
                realized_pnl_today=round(self._realized_today, 4),
                realized_pnl_total=round(self._realized_total, 4),
                paper=True,
                trades_opened_today=self.trades_opened_today(),
            )

    def get_positions(self) -> list[Position]:
        with self._lock:
            return list(self._positions.values())

    def get_open_orders(self) -> list[Order]:
        with self._lock:
            return [
                o for o in self._orders.values()
                if o.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED,
                                OrderStatus.PARTIALLY_FILLED)
            ]

    def get_orders(self) -> list[Order]:
        with self._lock:
            return list(self._orders.values())

    def get_trades(self) -> list[Trade]:
        with self._lock:
            return list(self._trades.values())

    def trades_opened_today(self) -> int:
        with self._lock:
            self._roll_day()
            return sum(
                1 for t in self._trades.values() if t.opened_at.date() == self._today
            )

    def consecutive_losses(self) -> int:
        """Losses since the most recent non-loss, within today's session."""
        with self._lock:
            closed = sorted(
                (t for t in self._trades.values() if t.closed_at is not None),
                key=lambda t: t.closed_at,  # type: ignore[arg-type,return-value]
                reverse=True,
            )
        streak = 0
        for trade in closed:
            if trade.result is TradeResult.LOSS:
                streak += 1
            else:
                break
        return streak

    # -- orders -------------------------------------------------------------
    def place_order(self, order: Order) -> Order:
        with self._lock:
            if order.client_order_id in {
                o.client_order_id for o in self._orders.values()
            }:
                order.status = OrderStatus.REJECTED
                order.rejection_reason = "duplicate client_order_id"
                return order

            price = order.limit_price or 0.0
            if price <= 0:
                order.status = OrderStatus.REJECTED
                order.rejection_reason = "no price available for a simulated fill"
                self._orders[order.order_id] = order
                return order

            # Simulated slippage: buys fill slightly worse than the limit.
            drift = 1.0 + self._slippage if order.side is OrderSide.BUY else 1.0 - self._slippage
            fill = price * drift
            fill = round(fill, 4)
            cost = fill * order.quantity

            if order.side is OrderSide.BUY:
                if cost > self._cash:
                    order.status = OrderStatus.REJECTED
                    order.rejection_reason = (
                        f"insufficient cash: need ${cost:,.2f}, have ${self._cash:,.2f}"
                    )
                    self._orders[order.order_id] = order
                    return order
                self._cash -= cost
                self._open_position(order, fill)
            else:
                self._close_position(order, fill)

            order.status = OrderStatus.FILLED
            order.filled_quantity = order.quantity
            order.avg_fill_price = fill
            order.submitted_at = order.submitted_at or datetime.now(UTC)
            order.filled_at = datetime.now(UTC)
            order.broker_order_id = f"paper-{order.order_id[:8]}"
            self._orders[order.order_id] = order
            return order

    def cancel_order(self, order_id: str) -> bool:
        with self._lock:
            order = self._orders.get(order_id)
            if order is None or order.status is not OrderStatus.PENDING:
                return False
            order.status = OrderStatus.CANCELLED
            return True

    def _open_position(self, order: Order, fill: float) -> None:
        ticker = order.ticker.upper()
        now = datetime.now(UTC)
        existing = self._positions.get(ticker)
        if existing is None:
            trade_id = f"{now.strftime('%Y%m%d')}-{ticker}-{len(self._trades) + 1:03d}"
            self._positions[ticker] = Position(
                ticker=ticker,
                quantity=order.quantity,
                avg_entry=fill,
                current_price=fill,
                stop=order.stop_price,
                strategy_id=order.strategy_id,
                signal_id=order.signal_id,
                trade_id=trade_id,
                opened_at=now,
                paper=True,
            )
            self._trades[trade_id] = Trade(
                trade_id=trade_id,
                ticker=ticker,
                strategy_id=order.strategy_id or "unknown",
                entry=fill,
                stop=order.stop_price or 0.0,
                target=0.0,
                quantity=order.quantity,
                opened_at=now,
                operating_mode=order.operating_mode,
                execution_source=order.execution_source,
                paper=True,
                signal_id=order.signal_id,
            )
        else:
            total_qty = existing.quantity + order.quantity
            existing.avg_entry = round(
                (existing.avg_entry * existing.quantity + fill * order.quantity) / total_qty, 4
            )
            existing.quantity = total_qty

    def _close_position(self, order: Order, fill: float) -> None:
        ticker = order.ticker.upper()
        position = self._positions.get(ticker)
        if position is None:
            order.rejection_reason = "no position to close"
            return

        quantity = min(order.quantity, position.quantity)
        proceeds = fill * quantity
        self._cash += proceeds
        realized = (fill - position.avg_entry) * quantity
        self._realized_total += realized
        self._roll_day()
        self._realized_today += realized

        if position.trade_id and position.trade_id in self._trades:
            trade = self._trades[position.trade_id]
            trade.exit_price = fill
            trade.closed_at = datetime.now(UTC)
            trade.exit_reason = order.rejection_reason or "manual_exit"
            trade.result = (
                TradeResult.WIN if realized > 0
                else TradeResult.LOSS if realized < 0
                else TradeResult.BREAKEVEN
            )

        position.quantity -= quantity
        if position.quantity <= 1e-9:
            del self._positions[ticker]

    # -- mark to market ------------------------------------------------------
    def sync(self, prices: dict[str, float]) -> None:
        """Mark positions to market and fire stop/target exits.

        The paper broker owns exit simulation: a live broker would have resting
        orders doing this, so the behaviour has to exist somewhere.
        """
        with self._lock:
            for ticker, position in list(self._positions.items()):
                price = prices.get(ticker)
                if price is None or price <= 0:
                    continue
                position.current_price = price

                hit_stop = position.stop is not None and price <= position.stop
                hit_target = position.target is not None and price >= position.target
                if not (hit_stop or hit_target):
                    continue

                exit_price = position.stop if hit_stop else position.target
                reason = "stop_loss" if hit_stop else "target_reached"
                exit_order = Order(
                    ticker=ticker,
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    quantity=position.quantity,
                    limit_price=exit_price,
                    signal_id=position.signal_id,
                    strategy_id=position.strategy_id,
                    paper=True,
                    created_at=datetime.now(UTC),
                )
                exit_order.rejection_reason = reason  # carried into trade.exit_reason
                self._close_position(exit_order, float(exit_price or price))
                exit_order.status = OrderStatus.FILLED
                exit_order.filled_quantity = exit_order.quantity
                exit_order.avg_fill_price = float(exit_price or price)
                exit_order.filled_at = datetime.now(UTC)
                exit_order.rejection_reason = None
                self._orders[exit_order.order_id] = exit_order

    def set_position_targets(self, ticker: str, stop: float, target: float) -> None:
        with self._lock:
            position = self._positions.get(ticker.upper())
            if position is None:
                return
            position.stop = stop
            position.target = target
            if position.trade_id and position.trade_id in self._trades:
                self._trades[position.trade_id].target = target
                self._trades[position.trade_id].stop = stop

    def _roll_day(self) -> None:
        today = datetime.now(UTC).date()
        if today != self._today:
            self._today = today
            self._realized_today = 0.0

    def reset(self) -> None:
        with self._lock:
            self._cash = self.starting_cash
            self._positions.clear()
            self._orders.clear()
            self._trades.clear()
            self._realized_total = 0.0
            self._realized_today = 0.0
