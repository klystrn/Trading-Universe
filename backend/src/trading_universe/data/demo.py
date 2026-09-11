"""Deterministic synthetic data (DEMO mode).

This is not decoration. It exists so the whole platform - scanner, scoring, risk
engine, paper execution, 3D universe - can be exercised end to end with zero
external dependencies, and so tests have a reproducible market to assert against.

Everything is seeded from the ticker string, so the same ticker always produces
the same history. Prices follow a geometric random walk with a per-sector drift
and a per-ticker volatility, plus deliberately planted setups (pullbacks,
squeezes, breakouts, oversold washouts) so each strategy has something to find.
"""

from __future__ import annotations

import hashlib
import math
import random
from datetime import UTC, date, datetime, timedelta

from trading_universe.data.base import MarketDataProvider
from trading_universe.domain.enums import (
    CatalystType,
    Chamber,
    PoliticalOwner,
    Session,
    TransactionType,
)
from trading_universe.domain.market import Candle, Quote
from trading_universe.domain.news import NewsArticle, SECEvent
from trading_universe.domain.political import PoliticalTransaction

# Per-sector annual drift and volatility used to shape the synthetic walk.
SECTOR_PROFILE: dict[str, tuple[float, float]] = {
    "information_technology": (0.18, 0.32),
    "communication_services": (0.12, 0.28),
    "consumer_discretionary": (0.10, 0.29),
    "health_care": (0.06, 0.22),
    "financials": (0.09, 0.24),
    "industrials": (0.08, 0.23),
    "consumer_staples": (0.04, 0.15),
    "energy": (0.05, 0.33),
    "utilities": (0.03, 0.16),
    "real_estate": (0.02, 0.21),
    "materials": (0.05, 0.25),
}

# Planted setup archetypes. Each ticker is assigned one deterministically so the
# demo universe contains a realistic mix rather than 477 identical random walks.
ARCHETYPES = [
    "uptrend_pullback",     # -> S1
    "catalyst_breakout",    # -> S2
    "oversold_washout",     # -> S3
    "volatility_squeeze",   # -> S4
    "value_reclaim",        # -> S5
    "plain_drift",          # -> no setup; most of the universe
    "plain_drift",
    "downtrend",
]

POSITIVE_HEADLINES = [
    "{name} raises full-year guidance on stronger demand",
    "{name} beats quarterly estimates as margins expand",
    "{name} announces multi-year supply agreement",
    "Analysts lift price targets on {name} after upbeat outlook",
    "{name} unveils next-generation product line",
]
NEGATIVE_HEADLINES = [
    "{name} cuts outlook amid softening orders",
    "{name} misses on revenue as costs climb",
    "Regulator opens review into {name} practices",
    "{name} flags inventory build heading into the quarter",
]
NEUTRAL_HEADLINES = [
    "{name} to present at industry conference",
    "{name} names new chief operating officer",
    "{name} schedules quarterly results date",
]

POLITICIANS = [
    ("Rep. A. Whitfield", Chamber.HOUSE, "D", "CA"),
    ("Rep. B. Callahan", Chamber.HOUSE, "R", "TX"),
    ("Rep. C. Ordonez", Chamber.HOUSE, "D", "NY"),
    ("Rep. D. Marchetti", Chamber.HOUSE, "R", "FL"),
    ("Rep. E. Nakamura", Chamber.HOUSE, "D", "WA"),
    ("Rep. F. Boland", Chamber.HOUSE, "R", "OH"),
    ("Sen. G. Hollis", Chamber.SENATE, "D", "IL"),
    ("Sen. H. Reyes", Chamber.SENATE, "R", "AZ"),
    ("Sen. I. Thornbury", Chamber.SENATE, "R", "GA"),
    ("Sen. J. Okafor", Chamber.SENATE, "D", "NJ"),
]

AMOUNT_BANDS = [
    (1001, 15000),
    (15001, 50000),
    (50001, 100000),
    (100001, 250000),
    (250001, 500000),
]


def _seed(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(digest[:16], 16)


def _rng(*parts: str) -> random.Random:
    return random.Random(_seed(*parts))


def archetype_for(ticker: str) -> str:
    return ARCHETYPES[_seed("archetype", ticker) % len(ARCHETYPES)]


def base_price_for(ticker: str) -> float:
    r = _rng("price", ticker)
    # Log-uniform between ~$12 and ~$650 - realistic spread of US large caps.
    return round(math.exp(r.uniform(math.log(12), math.log(650))), 2)


def _trading_days(end: date, count: int) -> list[date]:
    """Weekday sessions ending at ``end`` (holidays ignored - demo data)."""
    days: list[date] = []
    cursor = end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


class DemoMarket:
    """Generates and caches synthetic daily history for the whole universe."""

    def __init__(self, as_of: date | None = None, history_days: int = 300) -> None:
        self.as_of = as_of or datetime.now(UTC).date()
        self.history_days = history_days
        self._cache: dict[str, list[Candle]] = {}

    # -- candles ------------------------------------------------------------
    def candles(self, ticker: str, sector: str = "information_technology") -> list[Candle]:
        key = f"{ticker}:{self.as_of.isoformat()}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        drift_a, vol_a = SECTOR_PROFILE.get(sector, (0.08, 0.25))
        r = _rng("walk", ticker, self.as_of.isoformat())
        # Per-ticker tilt around the sector profile.
        drift = drift_a * r.uniform(0.3, 1.8) * (1.0 if r.random() > 0.25 else -0.6)
        vol = vol_a * r.uniform(0.7, 1.4)
        daily_drift = drift / 252.0
        daily_vol = vol / math.sqrt(252.0)

        archetype = archetype_for(ticker)
        days = _trading_days(self.as_of, self.history_days)
        n = len(days)
        price = base_price_for(ticker)
        base_volume = int(10 ** r.uniform(5.4, 7.3))

        closes: list[float] = []
        volumes: list[int] = []

        # Planted phases use ABSOLUTE daily drifts with capped noise. Scaling
        # them by the ticker's own volatility would let a high-vol name's noise
        # swamp the setup geometry, which is how a "controlled pullback" ends up
        # looking like a crash.
        quiet = min(daily_vol * 0.40, 0.0080)
        calm = min(daily_vol * 0.55, 0.0105)

        for i in range(n):
            from_end = n - 1 - i          # 0 on the most recent bar
            tail = max(0.0, (i - (n - 45)) / 45.0)
            d, v = daily_drift, daily_vol
            vol_mult = 1.0

            if archetype == "uptrend_pullback":
                if from_end > 40:
                    d, v = 0.0012, daily_vol
                elif from_end > 7:
                    d, v = 0.0034, calm          # established, orderly uptrend
                elif from_end > 1:
                    d, v, vol_mult = -0.0072, quiet, 0.88   # controlled pullback
                else:
                    d, v, vol_mult = 0.0082, quiet, 1.55    # buyers returning
            elif archetype == "catalyst_breakout":
                if from_end > 55:
                    d, v = daily_drift * 0.5, daily_vol
                elif from_end > 0:
                    d, v, vol_mult = 0.0002, quiet, 0.82    # base-building
                else:
                    # The catalyst gap lands on the newest bar, so the break of
                    # the prior 20-day high is the trade in front of us today.
                    d, v, vol_mult = 0.058, quiet, 3.3
            elif archetype == "oversold_washout":
                if from_end > 20:
                    d, v = 0.0008, daily_vol
                elif from_end > 2:
                    d, v, vol_mult = -0.0135, calm, 1.6     # sustained selling
                else:
                    d, v, vol_mult = 0.0090, quiet, 1.35    # selling exhausts
            elif archetype == "volatility_squeeze":
                # The compression must be SHORTER than the percentile lookback
                # (63 bars), or the quiet bars become their own baseline and the
                # squeeze stops registering as unusual.
                if from_end > 60:
                    d, v = daily_drift, daily_vol
                elif from_end > 24:
                    d, v = 0.0022, daily_vol            # mild advance into the base
                elif from_end > 0:
                    # Volatility and volume both wind down through the base.
                    squeeze_t = (24 - from_end) / 24.0
                    d = 0.0008
                    v = quiet * (0.55 - 0.35 * squeeze_t)
                    vol_mult = 0.74 - 0.22 * squeeze_t
                else:
                    d, v, vol_mult = 0.0290, quiet, 2.5     # expansion trigger
            elif archetype == "value_reclaim":
                if from_end > 60:
                    d, v = daily_drift, daily_vol
                elif from_end > 6:
                    d, v = -0.0040, calm                    # extended weakness
                else:
                    d, v, vol_mult = 0.0190, quiet, 1.50    # the 50DMA reclaim
            elif archetype == "downtrend":
                d = -abs(daily_drift) * 1.6 - 0.0009

            shock = r.gauss(0.0, 1.0) * v
            price = max(1.0, price * math.exp(d + shock))
            closes.append(price)
            volumes.append(max(1000, int(base_volume * vol_mult * r.uniform(0.70, 1.38))))

        out: list[Candle] = []
        prev_close = closes[0]
        for i, (day, close) in enumerate(zip(days, closes, strict=True)):
            rr = _rng("bar", ticker, day.isoformat())
            bar_vol = min(daily_vol, 0.02) if archetype != "plain_drift" else daily_vol
            intraday = abs(rr.gauss(0.0, bar_vol * 0.7)) + 0.0015
            open_ = prev_close * (1.0 + rr.gauss(0.0, bar_vol * 0.30))
            high = max(open_, close) * (1.0 + intraday * rr.uniform(0.25, 1.0))
            low = min(open_, close) * (1.0 - intraday * rr.uniform(0.25, 1.0))
            out.append(
                Candle(
                    ticker=ticker,
                    timestamp=datetime(day.year, day.month, day.day, 13, 30, tzinfo=UTC),
                    open=round(max(0.01, open_), 4),
                    high=round(max(0.01, high), 4),
                    low=round(max(0.01, min(low, open_, close)), 4),
                    close=round(close, 4),
                    volume=volumes[i],
                    interval="1d",
                )
            )
            prev_close = close

        self._cache[key] = out
        return out

    # -- quotes -------------------------------------------------------------
    def quote(
        self,
        ticker: str,
        sector: str = "information_technology",
        session: Session = Session.REGULAR,
        now: datetime | None = None,
    ) -> Quote:
        now = now or datetime.now(UTC)
        bars = self.candles(ticker, sector)
        last_bar = bars[-1]
        prev_close = bars[-2].close if len(bars) > 1 else last_bar.open

        # Small live wobble on top of the last close so the universe breathes.
        r = _rng("tick", ticker, now.strftime("%Y%m%d%H%M"))
        wobble = 1.0 + r.gauss(0.0, 0.0012)
        last = round(max(0.01, last_bar.close * wobble), 4)
        # Spread widens outside the regular session.
        spread_bps = 4.0 if session is Session.REGULAR else 22.0
        half = last * (spread_bps / 2.0) / 10_000.0

        return Quote(
            ticker=ticker,
            last=last,
            bid=round(last - half, 4),
            ask=round(last + half, 4),
            volume=last_bar.volume,
            prev_close=round(prev_close, 4),
            open=last_bar.open,
            high=last_bar.high,
            low=last_bar.low,
            session=session,
            event_time=now,
            received_time=now,
        )

    # -- news ---------------------------------------------------------------
    def news(
        self, ticker: str, name: str, now: datetime | None = None, days: int = 10
    ) -> list[NewsArticle]:
        now = now or datetime.now(UTC)
        archetype = archetype_for(ticker)
        r = _rng("news", ticker, now.date().isoformat())
        count = r.randint(0, 6)
        if archetype == "catalyst_breakout":
            count = max(count, 4)

        articles: list[NewsArticle] = []
        for i in range(count):
            age_hours = r.uniform(0.5, days * 24)
            published = now - timedelta(hours=age_hours)
            # Archetype biases which headline pool is drawn from.
            if archetype in ("catalyst_breakout", "uptrend_pullback"):
                pool, base = (POSITIVE_HEADLINES, 0.45) if r.random() < 0.75 else (
                    NEUTRAL_HEADLINES, 0.02
                )
            elif archetype in ("oversold_washout", "downtrend"):
                pool, base = (NEGATIVE_HEADLINES, -0.45) if r.random() < 0.70 else (
                    NEUTRAL_HEADLINES, 0.0
                )
            else:
                choice = r.random()
                if choice < 0.35:
                    pool, base = POSITIVE_HEADLINES, 0.30
                elif choice < 0.6:
                    pool, base = NEGATIVE_HEADLINES, -0.30
                else:
                    pool, base = NEUTRAL_HEADLINES, 0.0

            # An oversold washout's bad news must stop deteriorating for S3 to
            # fire, so decay negativity as it approaches the present.
            recency = 1.0 - min(1.0, age_hours / (days * 24))
            if archetype == "oversold_washout" and base < 0:
                base *= 1.0 - 0.7 * recency

            sentiment = max(-1.0, min(1.0, base + r.gauss(0.0, 0.12)))
            catalyst = None
            if archetype == "catalyst_breakout" and age_hours < 96 and r.random() < 0.6:
                catalyst = r.choice(
                    [
                        CatalystType.EARNINGS,
                        CatalystType.GUIDANCE,
                        CatalystType.CONTRACT,
                        CatalystType.PRODUCT,
                    ]
                )
            articles.append(
                NewsArticle(
                    article_id=f"demo-{ticker}-{int(published.timestamp())}-{i}",
                    tickers=[ticker],
                    title=r.choice(pool).format(name=name),
                    url=None,
                    source=r.choice(["GDELT", "Marketaux", "IR Feed", "SEC"]),
                    published_at=published,
                    discovered_at=published + timedelta(minutes=r.uniform(1, 25)),
                    processed_at=published + timedelta(minutes=r.uniform(26, 45)),
                    sentiment=round(sentiment, 4),
                    sentiment_engine="demo",
                    catalyst_type=catalyst,
                    salience=round(r.uniform(0.3, 1.0), 3),
                )
            )
        return sorted(articles, key=lambda a: a.published_at, reverse=True)

    # -- SEC ----------------------------------------------------------------
    def filings(self, ticker: str, now: datetime | None = None) -> list[SECEvent]:
        now = now or datetime.now(UTC)
        r = _rng("sec", ticker, now.date().isoformat())
        archetype = archetype_for(ticker)
        events: list[SECEvent] = []
        n = 2 if archetype == "catalyst_breakout" else r.randint(0, 2)
        for i in range(n):
            age_days = r.uniform(0.2, 40)
            filed = now - timedelta(days=age_days)
            form, items, ctype, strength = (
                ("8-K", ["2.02"], CatalystType.EARNINGS, 0.85)
                if i == 0 and archetype == "catalyst_breakout"
                else r.choice(
                    [
                        ("10-Q", [], None, 0.3),
                        ("8-K", ["7.01"], CatalystType.MANAGEMENT, 0.4),
                        ("8-K", ["1.01"], CatalystType.CONTRACT, 0.7),
                        ("10-K", [], None, 0.35),
                    ]
                )
            )
            events.append(
                SECEvent(
                    accession=f"demo-{ticker}-{i}-{int(filed.timestamp())}",
                    ticker=ticker,
                    form=form,
                    items=items,
                    title=f"{form} filing",
                    filed_at=filed,
                    discovered_at=filed + timedelta(minutes=r.uniform(1, 10)),
                    processed_at=filed + timedelta(minutes=r.uniform(11, 20)),
                    catalyst_type=ctype,
                    catalyst_strength=strength,
                )
            )
        return sorted(events, key=lambda e: e.filed_at, reverse=True)

    # -- fundamentals -------------------------------------------------------
    def fundamentals(self, ticker: str, sector: str) -> dict[str, float | bool | str]:
        r = _rng("fund", ticker)
        archetype = archetype_for(ticker)
        quality_tilt = {
            "uptrend_pullback": 0.75,
            "catalyst_breakout": 0.55,
            "oversold_washout": 0.80,   # S3 demands >=70 quality
            "volatility_squeeze": 0.65,
            "value_reclaim": 0.70,
            "plain_drift": 0.45,
            "downtrend": 0.25,
        }[archetype]

        revenue_yoy = round(r.gauss(0.06 + 0.10 * quality_tilt, 0.09), 4)
        margin = round(max(-0.1, r.gauss(0.10 + 0.18 * quality_tilt, 0.07)), 4)
        margin_change = round(r.gauss(0.004 * (quality_tilt * 2 - 1), 0.012), 5)
        fcf_positive = r.random() < (0.35 + 0.6 * quality_tilt)
        return {
            "revenue_yoy": revenue_yoy,
            "operating_margin": margin,
            "operating_margin_change": margin_change,
            "free_cash_flow": round(r.uniform(-2e9, 3e10) * (0.4 + quality_tilt), 0),
            "free_cash_flow_positive": fcf_positive,
            "fcf_yield": round(max(0.0, r.gauss(0.04 + 0.03 * quality_tilt, 0.025)), 4),
            "net_debt_to_ebitda": round(max(-2.0, r.gauss(2.4 - 1.6 * quality_tilt, 1.1)), 3),
            "debt_trend": "improving" if r.random() < quality_tilt else (
                "stable" if r.random() < 0.6 else "deteriorating"
            ),
            "roe": round(max(-0.3, r.gauss(0.08 + 0.22 * quality_tilt, 0.09)), 4),
            "roa": round(max(-0.2, r.gauss(0.03 + 0.12 * quality_tilt, 0.05)), 4),
            "share_count_change": round(r.gauss(-0.004 * quality_tilt, 0.012), 5),
            "earnings_consistency": round(min(1.0, max(0.0, r.gauss(quality_tilt, 0.15))), 3),
            "pe_ratio": round(max(3.0, r.gauss(28 - 12 * (1 - quality_tilt), 11)), 2),
            "source_form": "10-Q",
        }

    # -- political ----------------------------------------------------------
    def political(
        self, tickers: list[str], now: datetime | None = None, days: int = 180
    ) -> list[PoliticalTransaction]:
        """Plant disclosures so P1/P2/P3 each have something to find.

        Disclosure dates always trail transaction dates, matching the real
        reporting lag (spec 31).
        """
        now = now or datetime.now(UTC)
        today = now.date()
        r = _rng("political", today.isoformat())
        pool = sorted(tickers)
        if not pool:
            return []

        out: list[PoliticalTransaction] = []
        seq = 0

        def emit(
            ticker: str,
            politician: tuple[str, Chamber, str, str],
            txn_days_ago: float,
            lag_days: int,
            band_idx: int,
            ttype: TransactionType = TransactionType.PURCHASE,
            owner: PoliticalOwner = PoliticalOwner.SELF,
        ) -> None:
            nonlocal seq
            seq += 1
            txn_date = today - timedelta(days=int(txn_days_ago))
            disc_date = txn_date + timedelta(days=lag_days)
            if disc_date > today:
                disc_date = today
            lo, hi = AMOUNT_BANDS[band_idx]
            out.append(
                PoliticalTransaction(
                    transaction_id=f"demo-pol-{seq}",
                    politician=politician[0],
                    chamber=politician[1],
                    party=politician[2],
                    state=politician[3],
                    owner=owner,
                    ticker=ticker,
                    asset_description=f"{ticker} Common Stock",
                    transaction_type=ttype,
                    amount_low=float(lo),
                    amount_high=float(hi),
                    transaction_date=txn_date,
                    disclosure_date=disc_date,
                    detected_at=datetime(
                        disc_date.year, disc_date.month, disc_date.day, 14, 32, tzinfo=UTC
                    ),
                )
            )

        # P2 consensus: 3 politicians, both chambers, same name, recent.
        consensus_ticker = pool[_seed("consensus", today.isoformat()) % len(pool)]
        for i, pol in enumerate([POLITICIANS[0], POLITICIANS[3], POLITICIANS[7]]):
            emit(consensus_ticker, pol, txn_days_ago=26 - i * 5, lag_days=18, band_idx=1 + i % 3)

        # P3 repeat buyer: one politician, four purchases, no sales.
        repeat_ticker = pool[_seed("repeat", today.isoformat()) % len(pool)]
        for i in range(4):
            emit(repeat_ticker, POLITICIANS[6], txn_days_ago=150 - i * 38, lag_days=21,
                 band_idx=2 + (i % 2))

        # P1 fresh purchases: a handful of recent single disclosures.
        for i in range(6):
            t = pool[_seed("fresh", today.isoformat(), str(i)) % len(pool)]
            pol = POLITICIANS[(_seed("freshpol", str(i)) % len(POLITICIANS))]
            emit(t, pol, txn_days_ago=r.uniform(12, 30), lag_days=r.randint(9, 20),
                 band_idx=r.randint(0, 4),
                 owner=PoliticalOwner.SPOUSE if r.random() < 0.25 else PoliticalOwner.SELF)

        # Background noise, purchases and sales both.
        for i in range(28):
            t = pool[_seed("noise", today.isoformat(), str(i)) % len(pool)]
            pol = POLITICIANS[_seed("noisepol", str(i)) % len(POLITICIANS)]
            emit(
                t, pol,
                txn_days_ago=r.uniform(20, days),
                lag_days=r.randint(12, 42),
                band_idx=r.randint(0, 3),
                ttype=TransactionType.PURCHASE if r.random() < 0.55 else TransactionType.SALE,
            )

        return sorted(out, key=lambda p: p.disclosure_date, reverse=True)


class DemoMarketDataProvider(MarketDataProvider):
    """MarketDataProvider backed by :class:`DemoMarket`."""

    name = "demo"

    def __init__(self, market: DemoMarket | None = None) -> None:
        self._market = market or DemoMarket()
        self._connected = False
        self._subscribed: set[str] = set()

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def _sector(self, ticker: str) -> str:
        from trading_universe.data.universe import get_universe

        stock = get_universe().get(ticker)
        return stock.sector if stock else "information_technology"

    def get_quote(self, ticker: str) -> Quote | None:
        from trading_universe.services.sessions import current_session

        return self._market.quote(ticker, self._sector(ticker), session=current_session())

    def get_quotes(self, tickers: list[str]) -> dict[str, Quote]:
        out: dict[str, Quote] = {}
        for t in tickers:
            q = self.get_quote(t)
            if q is not None:
                out[t] = q
        return out

    def get_candles(self, ticker: str, interval: str = "1d", limit: int = 260) -> list[Candle]:
        bars = self._market.candles(ticker, self._sector(ticker))
        return bars[-limit:] if limit else bars

    def subscribe(self, tickers: list[str]) -> None:
        self._subscribed.update(tickers)

    def unsubscribe(self, tickers: list[str]) -> None:
        self._subscribed.difference_update(tickers)

    @property
    def subscribed(self) -> set[str]:
        return set(self._subscribed)
