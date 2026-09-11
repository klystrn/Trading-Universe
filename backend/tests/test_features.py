"""Feature engine: indicators, quality scoring, sentiment, regime."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from trading_universe.domain.market import Candle
from trading_universe.features.fundamentals import (
    build_fundamental_snapshot,
    quality_score,
)
from trading_universe.features.regime import classify, compute_breadth
from trading_universe.features.sentiment import (
    LexiconSentimentEngine,
    build_sentiment_snapshot,
)
from trading_universe.features.technical import (
    build_technical_snapshot,
    candles_to_frame,
    detect_bullish_engulfing,
    rsi,
)


def _series(values: list[float], ticker: str = "TEST") -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Candle(
            ticker=ticker,
            timestamp=start + timedelta(days=i),
            open=v * 0.995, high=v * 1.01, low=v * 0.99, close=v,
            volume=1_000_000, interval="1d",
        )
        for i, v in enumerate(values)
    ]


class TestIndicators:
    def test_rsi_is_100_for_an_unbroken_advance(self):
        frame = candles_to_frame(_series([100 + i for i in range(40)]))
        assert rsi(frame["close"]).iloc[-1] == pytest.approx(100.0, abs=0.01)

    def test_rsi_is_low_for_an_unbroken_decline(self):
        frame = candles_to_frame(_series([200 - i for i in range(40)]))
        assert rsi(frame["close"]).iloc[-1] < 5.0

    def test_rsi_is_mid_range_for_an_oscillation(self):
        values = [100 + 5 * math.sin(i / 2.0) for i in range(60)]
        frame = candles_to_frame(_series(values))
        assert 25.0 < rsi(frame["close"]).iloc[-1] < 75.0

    def test_insufficient_history_yields_none_not_a_wrong_number(self):
        snapshot = build_technical_snapshot("TEST", _series([100.0] * 10))
        assert snapshot.dma200 is None
        assert snapshot.dma50 is None
        assert snapshot.bars_available == 10

    def test_empty_candles_do_not_raise(self):
        snapshot = build_technical_snapshot("TEST", [])
        assert snapshot.bars_available == 0
        assert snapshot.close == 0.0

    def test_trend_flags_on_a_clean_uptrend(self):
        snapshot = build_technical_snapshot("TEST", _series([100 + i * 0.5 for i in range(260)]))
        assert snapshot.price_above_50dma
        assert snapshot.price_above_200dma
        assert snapshot.dma50_above_dma200

    def test_twenty_day_high_excludes_today(self):
        """'Broke the 20-day high' must mean clearing a level that pre-existed."""
        values = [100.0] * 40 + [120.0]
        snapshot = build_technical_snapshot("TEST", _series(values))
        assert snapshot.high_20 == pytest.approx(101.0, abs=0.01)
        assert snapshot.broke_20d_high

    def test_bullish_engulfing_detection(self):
        frame = candles_to_frame(
            [
                Candle(ticker="T", timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                       open=100, high=101, low=95, close=96, volume=1),
                Candle(ticker="T", timestamp=datetime(2026, 1, 2, tzinfo=UTC),
                       open=95, high=103, low=94, close=102, volume=1),
            ]
        )
        assert detect_bullish_engulfing(frame)

    def test_change_pct_uses_the_prior_close(self):
        snapshot = build_technical_snapshot("TEST", _series([100.0, 110.0]))
        assert snapshot.prev_close == 100.0
        assert snapshot.change_pct == pytest.approx(0.10)


class TestQualityScore:
    def test_a_strong_company_scores_high(self):
        snapshot = build_fundamental_snapshot(
            "GOOD",
            {
                "revenue_yoy": 0.22, "operating_margin_change": 0.025,
                "free_cash_flow_positive": True, "fcf_yield": 0.07,
                "net_debt_to_ebitda": 0.2, "roe": 0.28,
                "share_count_change": -0.015, "earnings_consistency": 1.0,
            },
        )
        assert snapshot.quality_score > 85

    def test_a_weak_company_scores_low(self):
        snapshot = build_fundamental_snapshot(
            "BAD",
            {
                "revenue_yoy": -0.12, "operating_margin_change": -0.03,
                "free_cash_flow_positive": False, "fcf_yield": -0.03,
                "net_debt_to_ebitda": 6.0, "roe": -0.05,
                "share_count_change": 0.09, "earnings_consistency": 0.0,
            },
        )
        assert snapshot.quality_score < 20

    def test_missing_data_lands_mid_scale_not_at_zero(self):
        """Absence of evidence must not be scored as evidence of weakness."""
        snapshot = build_fundamental_snapshot("UNKNOWN", {})
        assert 40 < snapshot.quality_score < 60

    def test_score_is_bounded(self):
        for facts in ({"roe": 99.0, "revenue_yoy": 50.0}, {"roe": -99.0, "revenue_yoy": -50.0}):
            assert 0.0 <= quality_score(build_fundamental_snapshot("X", facts)) <= 100.0


class TestSentiment:
    def test_lexicon_scores_direction_correctly(self):
        engine = LexiconSentimentEngine()
        assert engine.score("Company beats estimates and raises guidance") > 0.2
        assert engine.score("Company misses estimates and cuts outlook") < -0.2
        assert abs(engine.score("Company to present at a conference")) < 0.15

    def test_negation_flips_the_sign(self):
        engine = LexiconSentimentEngine()
        assert engine.score("did not beat estimates") < engine.score("did beat estimates")

    def test_empty_text_is_neutral(self):
        assert LexiconSentimentEngine().score("") == 0.0

    def test_aggregate_decays_with_age(self):
        from trading_universe.domain.news import NewsArticle

        now = datetime.now(UTC)
        articles = [
            NewsArticle(
                article_id="fresh", tickers=["T"], title="beats and raises",
                published_at=now - timedelta(hours=1), discovered_at=now, sentiment=0.9,
            ),
            NewsArticle(
                article_id="old", tickers=["T"], title="misses and cuts",
                published_at=now - timedelta(days=6), discovered_at=now, sentiment=-0.9,
            ),
        ]
        snapshot = build_sentiment_snapshot("T", articles, now=now)
        # The recent positive story should dominate the 7-day aggregate.
        assert snapshot.score_7d > 0
        assert snapshot.headline_count_24h == 1

    def test_no_coverage_is_flat_not_positive(self):
        snapshot = build_sentiment_snapshot("T", [], now=datetime.now(UTC))
        assert snapshot.score_7d == 0.0
        assert snapshot.trend == "flat"


class TestRegime:
    def test_breadth_computation(self, demo_provider, universe):
        snapshots = [
            build_technical_snapshot(t, demo_provider.get_candles(t))
            for t in universe.tickers()[:60]
        ]
        b20, b50, b200 = compute_breadth(snapshots)
        assert all(0.0 <= b <= 1.0 for b in (b20, b50, b200))

    def test_strong_bull_classification(self):
        from trading_universe.domain.enums import MarketRegime
        from trading_universe.domain.regime import RegimeInputs

        regime, confidence, reasons = classify(
            RegimeInputs(
                breadth_above_20dma=0.80, breadth_above_50dma=0.78,
                breadth_above_200dma=0.82, momentum_persistence=0.70,
                realized_vol_20d=0.012, news_sentiment=0.2,
                spy_above_50dma=True, spy_above_200dma=True,
            )
        )
        assert regime is MarketRegime.STRONG_BULL
        assert confidence > 0.7
        assert reasons

    def test_risk_off_classification(self):
        from trading_universe.domain.enums import MarketRegime
        from trading_universe.domain.regime import RegimeInputs

        regime, _, _ = classify(
            RegimeInputs(
                breadth_above_20dma=0.10, breadth_above_50dma=0.12,
                breadth_above_200dma=0.15, spy_above_200dma=False,
                realized_vol_20d=0.05, spy_drawdown_from_52w_high=-0.25,
            )
        )
        assert regime is MarketRegime.RISK_OFF

    def test_a_rally_inside_a_broken_tape_is_not_a_strong_bull(self):
        """Ordering matters: risk-off is evaluated before the bullish branches."""
        from trading_universe.domain.enums import MarketRegime
        from trading_universe.domain.regime import RegimeInputs

        regime, _, _ = classify(
            RegimeInputs(
                breadth_above_20dma=0.75, breadth_above_50dma=0.20,
                breadth_above_200dma=0.20, spy_above_200dma=False,
                momentum_persistence=0.80, realized_vol_20d=0.06,
            )
        )
        assert regime is not MarketRegime.STRONG_BULL

    def test_every_regime_yields_a_rationale(self):
        from trading_universe.domain.regime import RegimeInputs

        for breadth in (0.05, 0.3, 0.5, 0.7, 0.9):
            _, _, reasons = classify(
                RegimeInputs(
                    breadth_above_20dma=breadth, breadth_above_50dma=breadth,
                    breadth_above_200dma=breadth, momentum_persistence=breadth,
                )
            )
            assert reasons, f"no rationale at breadth {breadth}"
