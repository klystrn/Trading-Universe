"""Ingestion: populate the FeatureStore from whichever providers are configured.

DEMO mode synthesises everything locally. LIVE mode pulls SEC fundamentals,
GDELT/Marketaux news and congressional disclosures, scoring sentiment with the
local engine. Either way the FeatureStore ends up with the same snapshot types,
and every ingest records freshness so the risk engine can see how old the inputs
are.
"""

from __future__ import annotations

import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from trading_universe.data.demo import DemoMarket
from trading_universe.data.freshness import FreshnessService
from trading_universe.data.universe import UniverseRegistry
from trading_universe.domain.enums import DataMode
from trading_universe.domain.news import NewsArticle, SECEvent
from trading_universe.domain.political import PoliticalTransaction
from trading_universe.domain.snapshots import FundamentalSnapshot, SentimentSnapshot
from trading_universe.features.fundamentals import build_fundamental_snapshot
from trading_universe.features.political import summarize_by_ticker
from trading_universe.features.sentiment import build_sentiment_snapshot, get_sentiment_engine
from trading_universe.services.scanner import FeatureStore

logger = logging.getLogger(__name__)


class IngestService:
    def __init__(
        self,
        feature_store: FeatureStore,
        freshness: FreshnessService,
        universe: UniverseRegistry,
        data_mode: DataMode,
        repository=None,
    ) -> None:
        self.features = feature_store
        self.freshness = freshness
        self.universe = universe
        self.data_mode = data_mode
        self.repository = repository
        self._demo = DemoMarket() if data_mode is DataMode.DEMO else None
        self._sec = None
        self._gdelt = None
        self._marketaux = None
        self._house = None
        self._senate = None
        self._news_cache: dict[str, list[NewsArticle]] = {}
        self._filing_cache: dict[str, list[SECEvent]] = {}

    # -- lazy clients --------------------------------------------------------
    @property
    def sec(self):
        if self._sec is None:
            from trading_universe.data.sec import SECClient

            self._sec = SECClient()
        return self._sec

    @property
    def gdelt(self):
        if self._gdelt is None:
            from trading_universe.data.gdelt import GDELTClient

            self._gdelt = GDELTClient()
        return self._gdelt

    @property
    def marketaux(self):
        if self._marketaux is None:
            from trading_universe.data.marketaux import MarketauxClient

            self._marketaux = MarketauxClient()
        return self._marketaux

    @property
    def house(self):
        if self._house is None:
            from trading_universe.data.disclosures import HouseDisclosureClient

            self._house = HouseDisclosureClient()
        return self._house

    @property
    def senate(self):
        if self._senate is None:
            from trading_universe.data.disclosures import SenateDisclosureClient

            self._senate = SenateDisclosureClient()
        return self._senate

    # -- fundamentals --------------------------------------------------------
    def ingest_fundamentals(self, tickers: list[str]) -> int:
        now = datetime.now(UTC)
        out: dict[str, FundamentalSnapshot] = {}

        if self.data_mode is DataMode.DEMO and self._demo is not None:
            for ticker in tickers:
                stock = self.universe.get(ticker)
                if stock is None:
                    continue
                facts = self._demo.fundamentals(ticker, stock.sector)
                out[ticker] = build_fundamental_snapshot(ticker, facts, as_of=now)
        else:
            for ticker in tickers:
                facts = self.sec.get_company_facts(ticker)
                if facts is None:
                    continue
                filings = self._filings_for(ticker)
                filed = filings[0].filed_at if filings else None
                out[ticker] = build_fundamental_snapshot(
                    ticker, facts, as_of=now, filing_date=filed
                )

        self.features.set_fundamentals(out)
        return len(out)

    # -- news / sentiment -----------------------------------------------------
    def ingest_sentiment(self, tickers: list[str]) -> int:
        now = datetime.now(UTC)
        engine = get_sentiment_engine()
        out: dict[str, SentimentSnapshot] = {}

        if self.data_mode is DataMode.DEMO and self._demo is not None:
            for ticker in tickers:
                stock = self.universe.get(ticker)
                if stock is None:
                    continue
                articles = self._demo.news(ticker, stock.name, now=now)
                filings = self._demo.filings(ticker, now=now)
                self._news_cache[ticker] = articles
                self._filing_cache[ticker] = filings
                out[ticker] = build_sentiment_snapshot(
                    ticker, articles, filings, now=now, engine=engine
                )
            self.freshness.record("news_discovery", event_time=now, detail="demo generator")
            self.freshness.record("sec_filing", event_time=now, detail="demo generator")
        else:
            companies = {
                t: (self.universe.get(t).name if self.universe.get(t) else t) for t in tickers
            }
            articles = self.gdelt.fetch(companies, hours=48)
            if articles:
                self.freshness.record(
                    "news_discovery",
                    event_time=max(a.published_at for a in articles),
                    detail=f"GDELT: {len(articles)} articles",
                )
            else:
                self.freshness.mark_unavailable("news_discovery", "GDELT returned nothing")

            # Marketaux enriches only the names we care most about - the free
            # tier cannot cover the universe and pretending it can creates gaps.
            if self.marketaux.configured and self.marketaux.quota_remaining > 0:
                articles += self.marketaux.fetch(
                    tickers[:10], published_after=now - timedelta(days=2)
                )

            by_ticker: dict[str, list[NewsArticle]] = {}
            for article in articles:
                for ticker in article.tickers:
                    by_ticker.setdefault(ticker, []).append(article)

            for ticker in tickers:
                ticker_articles = by_ticker.get(ticker, [])
                filings = self._filings_for(ticker)
                self._news_cache[ticker] = ticker_articles
                out[ticker] = build_sentiment_snapshot(
                    ticker, ticker_articles, filings, now=now, engine=engine
                )

        self.features.set_sentiments(out)
        return len(out)

    def _filings_for(self, ticker: str) -> list[SECEvent]:
        cached = self._filing_cache.get(ticker)
        if cached is not None:
            return cached
        if self.data_mode is DataMode.DEMO and self._demo is not None:
            filings = self._demo.filings(ticker)
        else:
            filings = self.sec.get_recent_filings(ticker)
            if filings:
                self.freshness.record(
                    "sec_filing", event_time=filings[0].filed_at, detail=ticker
                )
        self._filing_cache[ticker] = filings
        return filings

    def news_for(self, ticker: str) -> list[NewsArticle]:
        return self._news_cache.get(ticker.upper(), [])

    def filings_for(self, ticker: str) -> list[SECEvent]:
        return self._filing_cache.get(ticker.upper(), [])

    # -- political -------------------------------------------------------------
    def ingest_political(self, tickers: list[str] | None = None) -> int:
        now = datetime.now(UTC)
        transactions: list[PoliticalTransaction] = []

        if self.data_mode is DataMode.DEMO and self._demo is not None:
            pool = tickers or self.universe.tickers()
            transactions = self._demo.political(pool, now=now)
        else:
            since = (now - timedelta(days=365)).date()
            for client in (self.house, self.senate):
                try:
                    transactions += client.fetch_disclosures(since=since)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s disclosures failed: %s", client.name, exc)
            if not transactions and self.repository is not None:
                # Fall back to whatever has already been imported rather than
                # silently reporting no political activity.
                transactions = self.repository.load_political_domain()

        if self.repository is not None and transactions:
            self.repository.save_political(transactions)

        universe_tickers = set(self.universe.tickers())
        relevant = [t for t in transactions if t.ticker in universe_tickers]
        snapshots = summarize_by_ticker(relevant, now=now)
        self.features.set_politicals(snapshots)

        if not relevant:
            self.freshness.mark_unavailable(
                "political_disclosure", "no disclosures loaded; import a PTR export"
            )
        return len(relevant)

    # -- everything ------------------------------------------------------------
    def ingest_all(self, tickers: list[str]) -> dict[str, int]:
        return {
            "fundamentals": self.ingest_fundamentals(tickers),
            "sentiment": self.ingest_sentiment(tickers),
            "political": self.ingest_political(tickers),
        }

    def close(self) -> None:
        for client in (self._sec, self._gdelt, self._marketaux, self._house, self._senate):
            if client is not None:
                with suppress(Exception):
                    client.close()
