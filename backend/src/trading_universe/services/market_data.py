"""Market data service with tiered subscriptions (spec section 25).

The whole S&P 500 + Nasdaq 100 is not subscribed at the highest frequency at
once. Instead:

    full universe -> periodic scan -> top ~30 (focus, real-time quotes)
    -> top ~10 (candidates, full evaluation every cycle)

Watchlisted names are always promoted to at least the focus tier. They receive
scan PRIORITY; they never receive a score bonus (spec section 69).
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

from trading_universe.config import get_config
from trading_universe.data.base import MarketDataProvider, ProviderError
from trading_universe.data.freshness import FreshnessService
from trading_universe.domain.market import Candle, Quote
from trading_universe.services.sessions import current_session

logger = logging.getLogger(__name__)


class MarketDataService:
    """Owns the quote/candle cache and which tier each ticker sits in."""

    def __init__(
        self, provider: MarketDataProvider, freshness: FreshnessService
    ) -> None:
        self.provider = provider
        self.freshness = freshness
        self._lock = threading.RLock()
        self._quotes: dict[str, Quote] = {}
        self._candles: dict[str, list[Candle]] = {}
        self._candles_fetched_at: dict[str, datetime] = {}
        self._focus: set[str] = set()
        self._candidates: set[str] = set()
        self._watchlist: set[str] = set()

    # -- connection ---------------------------------------------------------
    def connect(self) -> bool:
        try:
            ok = self.provider.connect()
        except Exception as exc:  # noqa: BLE001
            logger.error("market data provider connect failed: %s", exc)
            self.freshness.mark_unavailable("quote_active_candidate", str(exc))
            self.freshness.mark_unavailable("candle_daily", str(exc))
            return False
        return ok

    def disconnect(self) -> None:
        self.provider.disconnect()

    @property
    def connected(self) -> bool:
        return self.provider.connected

    # -- tiers --------------------------------------------------------------
    def set_watchlist(self, tickers: list[str]) -> None:
        with self._lock:
            self._watchlist = {t.upper() for t in tickers}

    def promote(self, focus: list[str], candidates: list[str]) -> None:
        """Set the focus and candidate tiers, re-subscribing as needed."""
        cfg = get_config().universe.tiers
        max_focus = int(cfg.get("focus", {}).get("max_symbols", 30))
        max_candidates = int(cfg.get("candidate", {}).get("max_symbols", 10))

        with self._lock:
            # Watchlist names are promoted into focus regardless of their score.
            new_focus = list(dict.fromkeys([*self._watchlist, *(t.upper() for t in focus)]))
            new_focus_set = set(new_focus[:max_focus])
            new_candidates = {t.upper() for t in candidates[:max_candidates]}

            added = (new_focus_set | new_candidates) - (self._focus | self._candidates)
            removed = (self._focus | self._candidates) - (new_focus_set | new_candidates)
            self._focus, self._candidates = new_focus_set, new_candidates

        if added:
            try:
                self.provider.subscribe(sorted(added))
            except Exception as exc:  # noqa: BLE001
                logger.warning("subscribe failed for %s: %s", sorted(added)[:5], exc)
        if removed:
            try:
                self.provider.unsubscribe(sorted(removed))
            except Exception as exc:  # noqa: BLE001
                logger.warning("unsubscribe failed: %s", exc)

    @property
    def focus(self) -> set[str]:
        return set(self._focus)

    @property
    def candidates(self) -> set[str]:
        return set(self._candidates)

    def tier_of(self, ticker: str) -> str:
        ticker = ticker.upper()
        if ticker in self._candidates:
            return "candidate"
        if ticker in self._focus:
            return "focus"
        return "broad"

    # -- data ---------------------------------------------------------------
    def refresh_quotes(self, tickers: list[str]) -> dict[str, Quote]:
        if not tickers:
            return {}
        try:
            quotes = self.provider.get_quotes([t.upper() for t in tickers])
        except (ProviderError, Exception) as exc:  # noqa: BLE001
            logger.warning("quote refresh failed: %s", exc)
            self.freshness.mark_unavailable("quote_active_candidate", str(exc))
            return {}

        now = datetime.now(UTC)
        with self._lock:
            self._quotes.update(quotes)

        if quotes:
            # Freshness is keyed off the OLDEST quote in the batch: reporting the
            # newest would hide a symbol whose feed has quietly stopped.
            oldest = min(q.event_time for q in quotes.values())
            self.freshness.record(
                "quote_active_candidate", event_time=oldest, received_time=now,
                detail=f"{len(quotes)} symbols",
            )
            if any(t in self._candidates or t in self._focus for t in quotes):
                self.freshness.record(
                    "quote_open_position", event_time=oldest, received_time=now
                )
        return quotes

    def get_quote(self, ticker: str) -> Quote | None:
        with self._lock:
            return self._quotes.get(ticker.upper())

    def quotes(self) -> dict[str, Quote]:
        with self._lock:
            return dict(self._quotes)

    def prices(self) -> dict[str, float]:
        with self._lock:
            return {t: q.last for t, q in self._quotes.items() if q.last > 0}

    def get_candles(
        self, ticker: str, interval: str = "1d", limit: int = 260, max_age_seconds: float = 3600.0
    ) -> list[Candle]:
        ticker = ticker.upper()
        key = f"{ticker}:{interval}"
        now = datetime.now(UTC)

        with self._lock:
            cached = self._candles.get(key)
            fetched = self._candles_fetched_at.get(key)
        if cached and fetched and (now - fetched).total_seconds() < max_age_seconds:
            return cached

        try:
            bars = self.provider.get_candles(ticker, interval=interval, limit=limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("candle fetch failed for %s: %s", ticker, exc)
            return cached or []

        with self._lock:
            self._candles[key] = bars
            self._candles_fetched_at[key] = now

        if bars:
            source = "candle_daily" if interval == "1d" else "candle_intraday"
            self.freshness.record(
                source, event_time=bars[-1].timestamp, received_time=now, detail=ticker
            )
        return bars

    def warm_candles(self, tickers: list[str], interval: str = "1d", limit: int = 260) -> int:
        loaded = 0
        for ticker in tickers:
            if self.get_candles(ticker, interval=interval, limit=limit):
                loaded += 1
        return loaded

    def session(self) -> str:
        return current_session().value

    def stats(self) -> dict[str, object]:
        with self._lock:
            return {
                "connected": self.connected,
                "provider": getattr(self.provider, "name", "unknown"),
                "quotes_cached": len(self._quotes),
                "candle_series_cached": len(self._candles),
                "focus": sorted(self._focus),
                "candidates": sorted(self._candidates),
                "watchlist": sorted(self._watchlist),
                "session": self.session(),
            }
