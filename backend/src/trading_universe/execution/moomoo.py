"""Moomoo OpenAPI adapter (spec sections 5, 23, 25).

Requires OpenD running locally and the optional ``[moomoo]`` extra. The import is
deferred so the platform runs without it; when the SDK is absent every method
raises :class:`BrokerError` and the health panel reports the source as
unavailable rather than the app failing to boot.

The API surface here follows the documented moomoo-api client
(https://openapi.moomoo.com/moomoo-api-doc/en/trade/overview.html). Revalidate
against the current docs before enabling live trading: entitlements, rate limits
and fractional-share support all change.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

from trading_universe.data.base import MarketDataProvider
from trading_universe.domain.enums import OrderSide, OrderStatus, OrderType, Session
from trading_universe.domain.market import Candle, Quote
from trading_universe.domain.portfolio import Order, Portfolio, Position
from trading_universe.execution.broker_base import BrokerBase, BrokerError
from trading_universe.settings import get_settings

logger = logging.getLogger(__name__)

_SDK_HINT = (
    "moomoo-api is not installed. Install with: pip install -e '.[moomoo]' "
    "and start OpenD (https://openapi.moomoo.com/)."
)


def _import_sdk():
    try:
        import moomoo  # type: ignore[import-not-found]

        return moomoo
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise BrokerError(_SDK_HINT) from exc


class MoomooMarketData(MarketDataProvider):
    """Quote and candle feed backed by OpenD."""

    name = "moomoo"

    def __init__(self, host: str | None = None, port: int | None = None) -> None:
        settings = get_settings()
        self.host = host or settings.moomoo_host
        self.port = port or settings.moomoo_port
        self._ctx = None
        self._lock = threading.RLock()
        self._subscribed: set[str] = set()

    # -- lifecycle ----------------------------------------------------------
    def connect(self) -> bool:
        with self._lock:
            if self._ctx is not None:
                return True
            sdk = _import_sdk()
            try:
                self._ctx = sdk.OpenQuoteContext(host=self.host, port=self.port)
                return True
            except Exception as exc:  # noqa: BLE001
                logger.error("Moomoo OpenD connection failed: %s", exc)
                self._ctx = None
                raise BrokerError(f"could not reach OpenD at {self.host}:{self.port}") from exc

    def disconnect(self) -> None:
        with self._lock:
            if self._ctx is not None:
                try:
                    self._ctx.close()
                finally:
                    self._ctx = None

    @property
    def connected(self) -> bool:
        return self._ctx is not None

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def to_moomoo_symbol(ticker: str) -> str:
        """AAPL -> US.AAPL. Dual-class dots become dashes (BRK.B -> US.BRK-B)."""
        return f"US.{ticker.upper().replace('.', '-')}"

    @staticmethod
    def from_moomoo_symbol(code: str) -> str:
        return code.split(".", 1)[-1].replace("-", ".").upper()

    def _require_ctx(self):
        if self._ctx is None:
            self.connect()
        if self._ctx is None:  # pragma: no cover - connect raises first
            raise BrokerError("Moomoo quote context unavailable")
        return self._ctx

    # -- data ---------------------------------------------------------------
    def get_quote(self, ticker: str) -> Quote | None:
        quotes = self.get_quotes([ticker])
        return quotes.get(ticker.upper())

    def get_quotes(self, tickers: list[str]) -> dict[str, Quote]:
        if not tickers:
            return {}
        ctx = self._require_ctx()
        codes = [self.to_moomoo_symbol(t) for t in tickers]
        # Snapshot is rate-limited; subscription push is the primary path for
        # anything in the focus/candidate tiers.
        ret, data = ctx.get_market_snapshot(codes)
        if ret != 0:
            raise BrokerError(f"get_market_snapshot failed: {data}")

        now = datetime.now(UTC)
        out: dict[str, Quote] = {}
        for row in data.to_dict("records"):
            ticker = self.from_moomoo_symbol(str(row.get("code", "")))
            event_time = self._parse_time(row.get("update_time")) or now
            out[ticker] = Quote(
                ticker=ticker,
                last=float(row.get("last_price") or 0.0),
                bid=self._opt_float(row.get("bid_price")),
                ask=self._opt_float(row.get("ask_price")),
                volume=int(row.get("volume") or 0),
                prev_close=self._opt_float(row.get("prev_close_price")),
                open=self._opt_float(row.get("open_price")),
                high=self._opt_float(row.get("high_price")),
                low=self._opt_float(row.get("low_price")),
                session=self._session_from(row),
                event_time=event_time,
                received_time=now,
            )
        return out

    def get_candles(self, ticker: str, interval: str = "1d", limit: int = 260) -> list[Candle]:
        ctx = self._require_ctx()
        sdk = _import_sdk()
        ktype = {
            "1d": sdk.KLType.K_DAY,
            "1m": sdk.KLType.K_1M,
            "5m": sdk.KLType.K_5M,
            "15m": sdk.KLType.K_15M,
            "60m": sdk.KLType.K_60M,
        }.get(interval, sdk.KLType.K_DAY)

        ret, data, _ = ctx.request_history_kline(
            self.to_moomoo_symbol(ticker), ktype=ktype, max_count=limit
        )
        if ret != 0:
            raise BrokerError(f"request_history_kline failed: {data}")

        out: list[Candle] = []
        for row in data.to_dict("records"):
            timestamp = self._parse_time(row.get("time_key"))
            if timestamp is None:
                continue
            out.append(
                Candle(
                    ticker=ticker.upper(),
                    timestamp=timestamp,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row.get("volume") or 0),
                    interval=interval,
                )
            )
        return out

    def subscribe(self, tickers: list[str]) -> None:
        if not tickers:
            return
        ctx = self._require_ctx()
        sdk = _import_sdk()
        codes = [self.to_moomoo_symbol(t) for t in tickers]
        ret, msg = ctx.subscribe(codes, [sdk.SubType.QUOTE, sdk.SubType.K_DAY])
        if ret != 0:
            raise BrokerError(f"subscribe failed: {msg}")
        self._subscribed.update(t.upper() for t in tickers)

    def unsubscribe(self, tickers: list[str]) -> None:
        if not tickers:
            return
        ctx = self._require_ctx()
        sdk = _import_sdk()
        codes = [self.to_moomoo_symbol(t) for t in tickers]
        ctx.unsubscribe(codes, [sdk.SubType.QUOTE, sdk.SubType.K_DAY])
        self._subscribed.difference_update(t.upper() for t in tickers)

    @property
    def subscribed(self) -> set[str]:
        return set(self._subscribed)

    # -- parsing ------------------------------------------------------------
    @staticmethod
    def _opt_float(value: object) -> float | None:
        try:
            out = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return out if out > 0 else None

    @staticmethod
    def _parse_time(value: object) -> datetime | None:
        if not value:
            return None
        try:
            from dateutil import parser
            from zoneinfo import ZoneInfo

            parsed = parser.parse(str(value))
            # OpenD reports US market times in US/Eastern without an offset.
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=ZoneInfo("America/New_York"))
            return parsed.astimezone(UTC)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _session_from(row: dict) -> Session:
        from trading_universe.services.sessions import current_session

        return current_session()


class MoomooBroker(BrokerBase):
    """Order placement through OpenD.

    ``paper=True`` selects the simulated trading environment. Constructing this
    with ``paper=False`` is gated by :class:`LiveBroker`, which checks the
    environment interlocks; do not instantiate it directly for real money.
    """

    name = "moomoo"

    def __init__(self, paper: bool = True, host: str | None = None, port: int | None = None) -> None:
        settings = get_settings()
        self.paper = paper
        self.host = host or settings.moomoo_host
        self.port = port or settings.moomoo_port
        self._ctx = None
        self._acc_id: int | None = None
        self._lock = threading.RLock()
        self._unlocked = False

    def connect(self) -> bool:
        with self._lock:
            if self._ctx is not None:
                return True
            sdk = _import_sdk()
            try:
                self._ctx = sdk.OpenSecTradeContext(
                    filter_trdmarket=sdk.TrdMarket.US, host=self.host, port=self.port
                )
            except Exception as exc:  # noqa: BLE001
                raise BrokerError(f"could not reach OpenD at {self.host}:{self.port}") from exc
            self._resolve_account()
            return True

    def disconnect(self) -> None:
        with self._lock:
            if self._ctx is not None:
                try:
                    self._ctx.close()
                finally:
                    self._ctx = None
                    self._unlocked = False

    @property
    def connected(self) -> bool:
        return self._ctx is not None

    @property
    def _trd_env(self):
        sdk = _import_sdk()
        return sdk.TrdEnv.SIMULATE if self.paper else sdk.TrdEnv.REAL

    def _resolve_account(self) -> None:
        settings = get_settings()
        configured = settings.moomoo_paper_account_id
        if configured:
            self._acc_id = int(configured)
            return
        ret, data = self._ctx.get_acc_list()  # type: ignore[union-attr]
        if ret != 0:
            raise BrokerError(f"get_acc_list failed: {data}")
        sdk = _import_sdk()
        wanted = sdk.TrdEnv.SIMULATE if self.paper else sdk.TrdEnv.REAL
        for row in data.to_dict("records"):
            if row.get("trd_env") == wanted:
                self._acc_id = int(row["acc_id"])
                return
        raise BrokerError(f"no {'simulated' if self.paper else 'real'} account found")

    def unlock_trade(self, password: str | None = None) -> bool:
        """Moomoo requires a trading unlock before real orders. Simulated
        accounts do not, but we keep the call symmetric."""
        if self.paper:
            self._unlocked = True
            return True
        password = password or get_settings().moomoo_trade_pwd
        if not password:
            raise BrokerError("MOOMOO_TRADE_PWD is required to unlock real trading")
        ret, data = self._ctx.unlock_trade(password)  # type: ignore[union-attr]
        if ret != 0:
            raise BrokerError(f"unlock_trade failed: {data}")
        self._unlocked = True
        return True

    @property
    def unlocked(self) -> bool:
        return self._unlocked

    def get_portfolio(self) -> Portfolio:
        ctx = self._require_ctx()
        ret, data = ctx.accinfo_query(trd_env=self._trd_env, acc_id=self._acc_id)
        if ret != 0:
            raise BrokerError(f"accinfo_query failed: {data}")
        row = data.to_dict("records")[0]
        return Portfolio(
            as_of=datetime.now(UTC),
            cash=float(row.get("cash") or 0.0),
            buying_power=float(row.get("power") or row.get("cash") or 0.0),
            positions=self.get_positions(),
            paper=self.paper,
        )

    def get_positions(self) -> list[Position]:
        ctx = self._require_ctx()
        ret, data = ctx.position_list_query(trd_env=self._trd_env, acc_id=self._acc_id)
        if ret != 0:
            raise BrokerError(f"position_list_query failed: {data}")
        out: list[Position] = []
        for row in data.to_dict("records"):
            quantity = float(row.get("qty") or 0.0)
            if quantity <= 0:
                continue
            out.append(
                Position(
                    ticker=MoomooMarketData.from_moomoo_symbol(str(row.get("code", ""))),
                    quantity=quantity,
                    avg_entry=float(row.get("cost_price") or 0.0),
                    current_price=float(row.get("nominal_price") or 0.0),
                    paper=self.paper,
                )
            )
        return out

    def get_open_orders(self) -> list[Order]:
        ctx = self._require_ctx()
        ret, data = ctx.order_list_query(trd_env=self._trd_env, acc_id=self._acc_id)
        if ret != 0:
            raise BrokerError(f"order_list_query failed: {data}")
        out: list[Order] = []
        for row in data.to_dict("records"):
            status = self._map_status(str(row.get("order_status", "")))
            if status not in (OrderStatus.SUBMITTED, OrderStatus.PENDING,
                              OrderStatus.PARTIALLY_FILLED):
                continue
            out.append(
                Order(
                    broker_order_id=str(row.get("order_id")),
                    client_order_id=str(row.get("remark") or row.get("order_id")),
                    ticker=MoomooMarketData.from_moomoo_symbol(str(row.get("code", ""))),
                    side=OrderSide.BUY if str(row.get("trd_side")) == "BUY" else OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=float(row.get("qty") or 0.0),
                    limit_price=float(row.get("price") or 0.0),
                    status=status,
                    filled_quantity=float(row.get("dealt_qty") or 0.0),
                    paper=self.paper,
                    created_at=MoomooMarketData._parse_time(row.get("create_time"))
                    or datetime.now(UTC),
                )
            )
        return out

    def place_order(self, order: Order) -> Order:
        if not self.paper and not self._unlocked:
            raise BrokerError("real trading is locked; call unlock_trade() first")
        ctx = self._require_ctx()
        sdk = _import_sdk()
        ret, data = ctx.place_order(
            price=order.limit_price,
            qty=order.quantity,
            code=MoomooMarketData.to_moomoo_symbol(order.ticker),
            trd_side=sdk.TrdSide.BUY if order.side is OrderSide.BUY else sdk.TrdSide.SELL,
            order_type=sdk.OrderType.NORMAL,
            trd_env=self._trd_env,
            acc_id=self._acc_id,
            # The client order id is our idempotency key; it comes back on the
            # order record so a reconnect can reconcile rather than re-submit.
            remark=order.client_order_id,
        )
        if ret != 0:
            order.status = OrderStatus.REJECTED
            order.rejection_reason = str(data)
            return order
        row = data.to_dict("records")[0]
        order.broker_order_id = str(row.get("order_id"))
        order.status = self._map_status(str(row.get("order_status", "")))
        order.submitted_at = datetime.now(UTC)
        order.paper = self.paper
        return order

    def cancel_order(self, order_id: str) -> bool:
        ctx = self._require_ctx()
        sdk = _import_sdk()
        ret, _ = ctx.modify_order(
            sdk.ModifyOrderOp.CANCEL, order_id, 0, 0,
            trd_env=self._trd_env, acc_id=self._acc_id,
        )
        return ret == 0

    def _require_ctx(self):
        if self._ctx is None:
            self.connect()
        if self._ctx is None:  # pragma: no cover
            raise BrokerError("Moomoo trade context unavailable")
        return self._ctx

    @staticmethod
    def _map_status(raw: str) -> OrderStatus:
        return {
            "SUBMITTING": OrderStatus.PENDING,
            "SUBMITTED": OrderStatus.SUBMITTED,
            "WAITING_SUBMIT": OrderStatus.PENDING,
            "FILLED_PART": OrderStatus.PARTIALLY_FILLED,
            "FILLED_ALL": OrderStatus.FILLED,
            "CANCELLED_ALL": OrderStatus.CANCELLED,
            "CANCELLED_PART": OrderStatus.CANCELLED,
            "FAILED": OrderStatus.REJECTED,
            "SUBMIT_FAILED": OrderStatus.REJECTED,
            "TIMEOUT": OrderStatus.EXPIRED,
            "DELETED": OrderStatus.CANCELLED,
        }.get(raw.upper(), OrderStatus.PENDING)
