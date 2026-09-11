"""Broker base class shared by the paper, Moomoo and live implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod

from trading_universe.domain.portfolio import Order, Portfolio, Position


class BrokerError(RuntimeError):
    """Broker-side failure. Callers degrade; they never retry blindly."""


class BrokerBase(ABC):
    name: str = "base"
    paper: bool = True

    @abstractmethod
    def connect(self) -> bool: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @property
    @abstractmethod
    def connected(self) -> bool: ...

    @abstractmethod
    def get_portfolio(self) -> Portfolio: ...

    @abstractmethod
    def get_positions(self) -> list[Position]: ...

    @abstractmethod
    def get_open_orders(self) -> list[Order]: ...

    @abstractmethod
    def place_order(self, order: Order) -> Order: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool: ...

    def sync(self, prices: dict[str, float]) -> None:
        """Mark positions to market. Default is a no-op for brokers that
        report their own valuations."""
        return None
