"""Provider protocols.

Every concrete data source implements one of these. The rest of the platform
depends on the protocol, never on Moomoo/SEC/GDELT specifics, which is what lets
DEMO mode substitute cleanly for LIVE.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, runtime_checkable

from trading_universe.domain.market import Candle, Quote
from trading_universe.domain.news import NewsArticle, SECEvent
from trading_universe.domain.political import PoliticalTransaction
from trading_universe.domain.portfolio import Order, Portfolio, Position


@runtime_checkable
class MarketDataProvider(Protocol):
    name: str

    def connect(self) -> bool: ...
    def disconnect(self) -> None: ...
    @property
    def connected(self) -> bool: ...

    def get_quote(self, ticker: str) -> Quote | None: ...
    def get_quotes(self, tickers: list[str]) -> dict[str, Quote]: ...
    def get_candles(
        self, ticker: str, interval: str = "1d", limit: int = 260
    ) -> list[Candle]: ...
    def subscribe(self, tickers: list[str]) -> None: ...
    def unsubscribe(self, tickers: list[str]) -> None: ...


@runtime_checkable
class FundamentalsProvider(Protocol):
    name: str

    def get_company_facts(self, ticker: str) -> dict[str, object] | None: ...
    def get_recent_filings(
        self, ticker: str, since: datetime | None = None
    ) -> list[SECEvent]: ...


@runtime_checkable
class NewsProvider(Protocol):
    name: str

    def fetch(
        self, tickers: list[str], since: datetime | None = None, limit: int = 100
    ) -> list[NewsArticle]: ...


@runtime_checkable
class PoliticalProvider(Protocol):
    name: str
    chamber: str

    def fetch_disclosures(
        self, since: date | None = None
    ) -> list[PoliticalTransaction]: ...


@runtime_checkable
class Broker(Protocol):
    """Order placement and account state.

    Implementations: PaperBroker (internal simulation), MoomooBroker (paper or
    real depending on the account passed), LiveBroker (MoomooBroker behind the
    additional safety interlocks).
    """

    name: str
    paper: bool

    def connect(self) -> bool: ...
    def disconnect(self) -> None: ...
    @property
    def connected(self) -> bool: ...

    def get_portfolio(self) -> Portfolio: ...
    def get_positions(self) -> list[Position]: ...
    def get_open_orders(self) -> list[Order]: ...
    def place_order(self, order: Order) -> Order: ...
    def cancel_order(self, order_id: str) -> bool: ...
    def sync(self, prices: dict[str, float]) -> None: ...


class ProviderError(RuntimeError):
    """Raised when a provider cannot serve a request. Callers must degrade
    gracefully and mark the source unavailable rather than propagating."""
