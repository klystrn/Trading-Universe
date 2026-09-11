"""The scanner: one full pass of the pipeline.

    universe -> features -> every strategy -> scoring -> regime selection
    -> risk validation -> (advisory | paper auto | live auto)

Note the ordering consequence: EVERY enabled strategy is evaluated on every
cycle, not only the active one. Other strategies keep producing signals for the
scanner, the universe and alerts; the risk engine is what stops them executing
(spec section 67).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from trading_universe.config import get_config
from trading_universe.data.freshness import FreshnessService
from trading_universe.data.universe import UniverseRegistry, get_universe
from trading_universe.domain.enums import ExecutionSource, OperatingMode
from trading_universe.domain.regime import (
    RegimeSnapshot,
    SectorRegime,
    StrategyRecommendation,
)
from trading_universe.domain.signals import Signal
from trading_universe.domain.snapshots import (
    FundamentalSnapshot,
    PoliticalSnapshot,
    SentimentSnapshot,
    TechnicalSnapshot,
)
from trading_universe.execution.engine import ExecutionEngine
from trading_universe.features.fundamentals import assign_value_percentiles
from trading_universe.features.regime import build_regime_snapshot
from trading_universe.features.sector import build_sector_regimes
from trading_universe.features.technical import build_technical_snapshot
from trading_universe.scoring.regime_selector import RegimeSelector
from trading_universe.scoring.scorer import SignalScorer
from trading_universe.services.market_data import MarketDataService
from trading_universe.strategies.base import StrategyContext, StrategyEvaluation
from trading_universe.strategies.registry import build_strategies

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ScanResult:
    started_at: datetime
    finished_at: datetime
    tickers_scanned: int
    signals: list[Signal] = field(default_factory=list)
    executable: list[Signal] = field(default_factory=list)
    near_misses: list[StrategyEvaluation] = field(default_factory=list)
    regime: RegimeSnapshot | None = None
    sector_regimes: list[SectorRegime] = field(default_factory=list)
    recommendation: StrategyRecommendation | None = None
    orders_placed: int = 0
    error: str | None = None
    # Snapshots are kept on the result so the visualization payload can be built
    # without recomputing indicators for the whole universe on every push.
    technicals: dict[str, TechnicalSnapshot] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        return round((self.finished_at - self.started_at).total_seconds(), 3)

    @property
    def rejected_count(self) -> int:
        return len(self.signals) - len(self.executable)


class Scanner:
    def __init__(
        self,
        market_data: MarketDataService,
        freshness: FreshnessService,
        execution: ExecutionEngine,
        feature_store: FeatureStore,
        universe: UniverseRegistry | None = None,
        repository=None,
    ) -> None:
        self.market_data = market_data
        self.freshness = freshness
        self.execution = execution
        self.features = feature_store
        self.universe = universe or get_universe()
        self.repository = repository
        self.scorer = SignalScorer(freshness)
        self.selector = RegimeSelector()
        self._last_result: ScanResult | None = None

    @property
    def last_result(self) -> ScanResult | None:
        return self._last_result

    # -- the cycle ----------------------------------------------------------
    def run(
        self,
        tickers: list[str] | None = None,
        execute: bool = True,
        now: datetime | None = None,
    ) -> ScanResult:
        started = now or datetime.now(UTC)
        tickers = [t.upper() for t in (tickers or self.universe.tickers())]
        scan_id = self.repository.start_scan(started) if self.repository else None

        try:
            result = self._run_inner(tickers, execute, started)
        except Exception as exc:  # noqa: BLE001 - a scan must never kill the app
            logger.exception("scan failed")
            result = ScanResult(
                started_at=started,
                finished_at=datetime.now(UTC),
                tickers_scanned=0,
                error=str(exc),
            )

        if self.repository and scan_id is not None:
            self.repository.finish_scan(
                scan_id,
                result.finished_at,
                result.tickers_scanned,
                len(result.signals),
                len(result.executable),
                result.rejected_count,
                result.regime.regime.value if result.regime else None,
                result.error,
            )
        self._last_result = result
        return result

    def _run_inner(
        self, tickers: list[str], execute: bool, started: datetime
    ) -> ScanResult:
        # --- 1. features ---------------------------------------------------
        technicals = self.features.technicals(tickers)
        fundamentals = self.features.fundamentals(tickers)
        assign_value_percentiles(fundamentals)
        sentiments = self.features.sentiments(tickers)
        politicals = self.features.politicals(tickers)

        # --- 2. regimes -----------------------------------------------------
        snaps = list(technicals.values())
        by_sector: dict[str, list[TechnicalSnapshot]] = defaultdict(list)
        for snap in snaps:
            by_sector[self.universe.sector_of(snap.ticker)].append(snap)

        sector_regimes, dispersion = build_sector_regimes(
            dict(by_sector), sentiments, politicals
        )
        regime = build_regime_snapshot(
            snaps, sentiments=sentiments, sector_dispersion=dispersion, now=started
        )
        sector_by_id = {s.sector_id: s for s in sector_regimes}

        # --- 3. strategies ---------------------------------------------------
        strategies = build_strategies(only_enabled=True)
        signals: list[Signal] = []
        near_misses: list[StrategyEvaluation] = []
        counts_by_strategy: dict[str, int] = defaultdict(int)
        counts_by_sector: dict[str, int] = defaultdict(int)

        for ticker in tickers:
            technical = technicals.get(ticker)
            stock = self.universe.get(ticker)
            if technical is None or stock is None:
                continue

            ctx = StrategyContext(
                ticker=ticker,
                stock=stock,
                technical=technical,
                fundamental=fundamentals.get(ticker) or _empty_fundamental(ticker, started),
                sentiment=sentiments.get(ticker) or SentimentSnapshot(ticker=ticker, as_of=started),
                now=started,
                quote=self.market_data.get_quote(ticker),
                candles=self.market_data.get_candles(ticker),
                political=politicals.get(ticker),
                regime=regime,
                sector_regime=sector_by_id.get(stock.sector),
            )

            for strategy in strategies.values():
                try:
                    evaluation = strategy.evaluate(ctx)
                except Exception as exc:  # noqa: BLE001 - one bad ticker must not
                    # abort the scan; the error belongs to that strategy alone.
                    logger.warning(
                        "%s failed on %s: %s", strategy.id, ticker, exc, exc_info=False
                    )
                    continue

                if not evaluation.setup_present:
                    if evaluation.near_miss:
                        near_misses.append(evaluation)
                    continue

                assert evaluation.proposal is not None
                signal = self.scorer.build_signal(
                    evaluation.proposal, ctx, strategy, now=started
                )
                signals.append(signal)
                counts_by_strategy[strategy.id] += 1
                counts_by_sector[stock.sector] += 1

        for sector_regime in sector_regimes:
            sector_regime.signal_count = counts_by_sector.get(sector_regime.sector_id, 0)

        # --- 4. the daily recommendation ---------------------------------------
        recommendation = self.selector.recommend(
            regime,
            sector_regimes,
            signal_counts_by_strategy=dict(counts_by_strategy),
            trading_day=started.date(),
            now=started,
        )
        recommendation.active_strategy = self.execution.active_strategy

        # --- 5. tier promotion ----------------------------------------------------
        ranked = sorted(signals, key=lambda s: s.score.total, reverse=True)
        cfg = get_config().universe.tiers
        max_focus = int(cfg.get("focus", {}).get("max_symbols", 30))
        max_candidates = int(cfg.get("candidate", {}).get("max_symbols", 10))
        focus = list(dict.fromkeys(s.ticker for s in ranked))[:max_focus]
        candidates = focus[:max_candidates]
        self.market_data.promote(focus, candidates)
        # Now that the best names are subscribed, refresh their quotes so risk
        # validation runs against genuinely current prices.
        if focus:
            self.market_data.refresh_quotes(focus)

        # --- 6. risk validation and execution --------------------------------------
        executable: list[Signal] = []
        orders_placed = 0
        risk_ctx = self.execution.build_context(now=started)

        for signal in ranked:
            technical = technicals.get(signal.ticker)
            quote = self.market_data.get_quote(signal.ticker)
            risk_ctx.technical = technical
            risk_ctx.quote = quote

            if execute and self.execution.operating_mode is not OperatingMode.ADVISORY:
                decision, order, thesis = self.execution.process(
                    signal, risk_ctx, ExecutionSource.AUTO
                )
                if order is not None:
                    orders_placed += 1
                    # Refresh capacity so the next signal sees the new position.
                    risk_ctx = self.execution.build_context(now=started)
            else:
                decision = self.execution.risk.validate(signal, risk_ctx)
                signal.execution = decision
                from trading_universe.thesis.builder import build_thesis

                thesis = build_thesis(signal, accepted=decision.allowed)

            if decision.allowed:
                executable.append(signal)
            if self.repository is not None:
                self.repository.save_thesis(thesis)

        # --- 7. persist ---------------------------------------------------------------
        if self.repository is not None:
            self.repository.save_signals(signals)
            self.repository.save_recommendation(recommendation)

        return ScanResult(
            started_at=started,
            finished_at=datetime.now(UTC),
            tickers_scanned=len(tickers),
            signals=ranked,
            executable=executable,
            near_misses=near_misses[:200],
            regime=regime,
            sector_regimes=sector_regimes,
            recommendation=recommendation,
            orders_placed=orders_placed,
            technicals=technicals,
        )


def _empty_fundamental(ticker: str, as_of: datetime) -> FundamentalSnapshot:
    """A ticker with no filings scores zero quality, not a neutral default:
    absence of evidence is not evidence of quality."""
    return FundamentalSnapshot(ticker=ticker, as_of=as_of, quality_score=0.0)


class FeatureStore:
    """Builds and caches the four snapshot families for a scan cycle."""

    def __init__(
        self,
        market_data: MarketDataService,
        freshness: FreshnessService,
        universe: UniverseRegistry | None = None,
    ) -> None:
        self.market_data = market_data
        self.freshness = freshness
        self.universe = universe or get_universe()
        self._fundamentals: dict[str, FundamentalSnapshot] = {}
        self._sentiments: dict[str, SentimentSnapshot] = {}
        self._politicals: dict[str, PoliticalSnapshot] = {}

    def technicals(self, tickers: list[str]) -> dict[str, TechnicalSnapshot]:
        out: dict[str, TechnicalSnapshot] = {}
        for ticker in tickers:
            bars = self.market_data.get_candles(ticker)
            if not bars:
                continue
            out[ticker] = build_technical_snapshot(ticker, bars)
        return out

    def fundamentals(self, tickers: list[str]) -> dict[str, FundamentalSnapshot]:
        return {t: self._fundamentals[t] for t in tickers if t in self._fundamentals}

    def sentiments(self, tickers: list[str]) -> dict[str, SentimentSnapshot]:
        return {t: self._sentiments[t] for t in tickers if t in self._sentiments}

    def politicals(self, tickers: list[str]) -> dict[str, PoliticalSnapshot]:
        return {t: self._politicals[t] for t in tickers if t in self._politicals}

    # -- population ----------------------------------------------------------
    def set_fundamentals(self, data: dict[str, FundamentalSnapshot]) -> None:
        self._fundamentals.update(data)
        if data:
            newest = max(s.as_of for s in data.values())
            self.freshness.record(
                "fundamental_ratios", event_time=newest, detail=f"{len(data)} tickers"
            )

    def set_sentiments(self, data: dict[str, SentimentSnapshot]) -> None:
        self._sentiments.update(data)
        if data:
            newest = max(s.as_of for s in data.values())
            self.freshness.record(
                "news_sentiment_aggregate", event_time=newest, detail=f"{len(data)} tickers"
            )

    def set_politicals(self, data: dict[str, PoliticalSnapshot]) -> None:
        self._politicals.update(data)
        if data:
            self.freshness.record(
                "political_disclosure",
                event_time=max(
                    (s.newest_disclosure_at for s in data.values() if s.newest_disclosure_at),
                    default=datetime.now(UTC),
                ),
                detail=f"{len(data)} tickers",
            )
