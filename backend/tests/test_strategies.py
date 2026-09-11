"""Strategy contract and behaviour.

Two invariants matter most here:
  * a strategy can only ever produce a proposal, never an order;
  * every strategy's minimum reward:risk is respected in its own geometry.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trading_universe.data.demo import archetype_for
from trading_universe.domain.snapshots import (
    FundamentalSnapshot,
    SentimentSnapshot,
)
from trading_universe.features.technical import build_technical_snapshot
from trading_universe.strategies.base import StrategyContext
from trading_universe.strategies.registry import (
    STRATEGY_BY_ID,
    build_strategies,
    build_strategy,
)


def _context(ticker, universe, provider, **overrides):
    now = datetime.now(UTC)
    candles = provider.get_candles(ticker)
    defaults = dict(
        ticker=ticker,
        stock=universe.get(ticker),
        technical=build_technical_snapshot(ticker, candles),
        fundamental=FundamentalSnapshot(
            ticker=ticker, as_of=now, quality_score=80.0,
            # The gates check these explicitly; leaving them unset is correctly
            # treated as "unproven", not "fine".
            revenue_yoy=0.12, operating_margin=0.22, operating_margin_change=0.01,
            free_cash_flow=5e9, free_cash_flow_positive=True, fcf_yield=0.05,
            net_debt_to_ebitda=1.0, debt_trend="stable", roe=0.2,
            share_count_change=-0.01, earnings_consistency=0.9,
            value_percentile=75.0,
        ),
        sentiment=SentimentSnapshot(
            ticker=ticker, as_of=now, score_24h=0.3, score_7d=0.2,
            headline_count_7d=5, headline_count_24h=2, trend="improving",
        ),
        now=now,
        candles=candles,
    )
    defaults.update(overrides)
    return StrategyContext(**defaults)


class TestContract:
    def test_all_eight_strategies_are_registered(self):
        assert len(STRATEGY_BY_ID) == 8
        assert set(STRATEGY_BY_ID) == {
            "quality_momentum_pullback",
            "fundamental_catalyst_breakout",
            "quality_oversold_reversal",
            "quality_volatility_squeeze",
            "value_rerating_50dma_reclaim",
            "congress_fresh_purchase",
            "congress_consensus",
            "congress_repeat_buyer",
        }

    def test_no_strategy_can_reach_a_broker(self):
        """Spec 4: strategies never place orders."""
        for strategy in build_strategies().values():
            for attribute in ("broker", "place_order", "execute", "submit"):
                assert not hasattr(strategy, attribute), (
                    f"{strategy.id} exposes {attribute}"
                )

    def test_strategies_never_set_their_own_score(self, universe, demo_provider):
        """Scoring is a separate layer; a proposal carries only 0-1 fits."""
        for ticker in universe.tickers()[:40]:
            ctx = _context(ticker, universe, demo_provider)
            for strategy in build_strategies().values():
                evaluation = strategy.evaluate(ctx)
                if evaluation.proposal is None:
                    continue
                proposal = evaluation.proposal
                assert not hasattr(proposal, "score")
                for fit in (
                    proposal.technical_fit, proposal.sentiment_fit, proposal.fundamental_fit
                ):
                    assert 0.0 <= fit <= 1.0

    def test_a_failed_evaluation_explains_why(self, universe, demo_provider):
        strategy = build_strategy("quality_momentum_pullback")
        found_failure = False
        for ticker in universe.tickers()[:30]:
            evaluation = strategy.evaluate(_context(ticker, universe, demo_provider))
            if not evaluation.setup_present:
                assert evaluation.failed_checks, f"{ticker} failed with no reason given"
                found_failure = True
        assert found_failure


class TestGeometry:
    def test_every_proposal_meets_its_minimum_reward_risk(self, universe, demo_provider):
        """The rounding of a target must never shave R:R below the minimum."""
        checked = 0
        for ticker in universe.tickers():
            ctx = _context(ticker, universe, demo_provider)
            for strategy in build_strategies().values():
                evaluation = strategy.evaluate(ctx)
                if evaluation.proposal is None:
                    continue
                p = evaluation.proposal
                risk = p.entry - p.stop
                assert risk > 0, f"{strategy.id}/{ticker}: non-positive risk"
                rr = (p.target - p.entry) / risk
                assert rr >= strategy.minimum_reward_risk - 1e-9, (
                    f"{strategy.id}/{ticker}: {rr:.6f}R below "
                    f"{strategy.minimum_reward_risk}"
                )
                checked += 1
        assert checked > 0, "no proposals produced - the fixture is not exercising anything"

    def test_stops_are_technical_not_fixed_percentages(self, universe, demo_provider):
        """Spec 2: technical invalidation is the primary stop methodology."""
        distances = []
        for ticker in universe.tickers():
            ctx = _context(ticker, universe, demo_provider)
            evaluation = build_strategy("quality_momentum_pullback").evaluate(ctx)
            if evaluation.proposal is None:
                continue
            p = evaluation.proposal
            distances.append((p.entry - p.stop) / p.entry)
        assert len(distances) > 3
        # A fixed-percentage stop would give an identical distance every time.
        assert len(set(round(d, 4) for d in distances)) > 1

    def test_stop_is_always_below_entry(self, universe, demo_provider):
        for ticker in universe.tickers()[:120]:
            ctx = _context(ticker, universe, demo_provider)
            for strategy in build_strategies().values():
                evaluation = strategy.evaluate(ctx)
                if evaluation.proposal is not None:
                    assert evaluation.proposal.stop < evaluation.proposal.entry


class TestMomentumPullback:
    def test_requires_an_established_uptrend(self, universe, demo_provider):
        """A downtrend name must never produce a momentum-pullback signal."""
        downtrend = [t for t in universe.tickers() if archetype_for(t) == "downtrend"]
        strategy = build_strategy("quality_momentum_pullback")
        for ticker in downtrend[:25]:
            evaluation = strategy.evaluate(_context(ticker, universe, demo_provider))
            if evaluation.setup_present:
                pytest.fail(f"{ticker} is in a downtrend but produced a pullback signal")

    def test_fires_on_the_planted_pullback_archetype(self, universe, demo_provider):
        pullbacks = [t for t in universe.tickers() if archetype_for(t) == "uptrend_pullback"]
        strategy = build_strategy("quality_momentum_pullback")
        hits = sum(
            strategy.evaluate(_context(t, universe, demo_provider)).setup_present
            for t in pullbacks
        )
        assert hits > 0

    def test_weak_fundamentals_block_the_setup(self, universe, demo_provider):
        pullbacks = [t for t in universe.tickers() if archetype_for(t) == "uptrend_pullback"]
        strategy = build_strategy("quality_momentum_pullback")
        ticker = next(
            t for t in pullbacks
            if strategy.evaluate(_context(t, universe, demo_provider)).setup_present
        )
        weak = FundamentalSnapshot(
            ticker=ticker, as_of=datetime.now(UTC), quality_score=10.0,
            revenue_yoy=-0.2, free_cash_flow_positive=False,
        )
        evaluation = strategy.evaluate(
            _context(ticker, universe, demo_provider, fundamental=weak)
        )
        assert not evaluation.setup_present


class TestCatalystBreakout:
    def test_rejects_a_headline_with_no_volume(self, universe, demo_provider):
        """Spec 10's explicit rejection: great headline, no confirmation."""
        from trading_universe.domain.enums import CatalystType

        strategy = build_strategy("fundamental_catalyst_breakout")
        breakouts = [t for t in universe.tickers() if archetype_for(t) == "catalyst_breakout"]
        blocked_for_volume = 0
        for ticker in breakouts[:20]:
            technical = build_technical_snapshot(ticker, demo_provider.get_candles(ticker))
            technical.volume_ratio = 0.4          # no market confirmation
            sentiment = SentimentSnapshot(
                ticker=ticker, as_of=datetime.now(UTC), score_24h=0.9, score_7d=0.8,
                headline_count_24h=9, catalyst_type=CatalystType.EARNINGS,
                catalyst_strength=0.95, catalyst_sessions_ago=1,
            )
            evaluation = strategy.evaluate(
                _context(ticker, universe, demo_provider,
                         technical=technical, sentiment=sentiment)
            )
            assert not evaluation.setup_present
            if any("volume" in f for f in evaluation.failed_checks):
                blocked_for_volume += 1
        assert blocked_for_volume > 0

    def test_requires_a_catalyst_at_all(self, universe, demo_provider):
        strategy = build_strategy("fundamental_catalyst_breakout")
        breakouts = [t for t in universe.tickers() if archetype_for(t) == "catalyst_breakout"]
        for ticker in breakouts[:10]:
            neutral = SentimentSnapshot(
                ticker=ticker, as_of=datetime.now(UTC), score_24h=0.4, score_7d=0.3,
                headline_count_24h=3,
            )
            evaluation = strategy.evaluate(
                _context(ticker, universe, demo_provider, sentiment=neutral)
            )
            assert not evaluation.setup_present
            assert any("catalyst" in f for f in evaluation.failed_checks)


class TestOversoldReversal:
    def test_rsi_alone_is_not_enough(self, universe, demo_provider):
        """Spec 11: do not buy merely because RSI is 27."""
        strategy = build_strategy("quality_oversold_reversal")
        washouts = [t for t in universe.tickers() if archetype_for(t) == "oversold_washout"]
        ticker = washouts[0]
        technical = build_technical_snapshot(ticker, demo_provider.get_candles(ticker))
        technical.rsi14 = 27.0
        technical.rsi_recently_oversold = True
        technical.rsi_turning_up = True
        # Strip every piece of reversal evidence, keeping only the low RSI.
        technical.higher_low = False
        technical.bullish_engulfing = False
        technical.vwap_reclaimed = False
        evaluation = strategy.evaluate(
            _context(ticker, universe, demo_provider, technical=technical)
        )
        assert not evaluation.setup_present
        assert any("reversal" in f for f in evaluation.failed_checks)

    def test_demands_high_fundamental_quality(self, universe, demo_provider):
        strategy = build_strategy("quality_oversold_reversal")
        assert strategy.cfg("fundamentals.min_quality_score") == 70


class TestPolitical:
    def test_a_disclosure_alone_never_triggers(self, universe, demo_provider):
        """Spec 14: political activity is a signal generator, not copy-trading.

        The invariant is about technical CONFIRMATION, not about the name's
        longer-run drift: a weak stock that has genuinely reclaimed its 50DMA
        and is retesting its highs does have confirmation. So this strips the
        confirmation explicitly and asserts the political evidence alone -
        however overwhelming - cannot carry the trade.
        """
        from trading_universe.domain.snapshots import PoliticalSnapshot

        now = datetime.now(UTC)
        overwhelming = PoliticalSnapshot(
            ticker="TEST", as_of=now, purchases_30d=5, distinct_politicians_30d=5,
            newest_disclosure_age_days=1.0, newest_transaction_lag_days=14.0,
            largest_band_usd=500_000.0, consensus_score=1.0, freshness_score=1.0,
            repeat_score=1.0, chambers_30d=["HOUSE", "SENATE"],
            repeat_buyers={"Sen. X|SELF": 5},
        )

        for strategy_id in (
            "congress_fresh_purchase", "congress_consensus", "congress_repeat_buyer"
        ):
            strategy = build_strategy(strategy_id)
            for ticker in universe.tickers()[:25]:
                technical = build_technical_snapshot(
                    ticker, demo_provider.get_candles(ticker)
                )
                # No confirmation of any kind: below the 50DMA, no reclaim,
                # nothing breaking out, momentum still falling.
                technical.price_above_50dma = False
                technical.reclaimed_50dma = False
                technical.rsi_turning_up = False
                technical.close = min(technical.close, (technical.dma50 or 1e9) * 0.90)

                political = overwhelming.model_copy(update={"ticker": ticker})
                evaluation = strategy.evaluate(
                    _context(
                        ticker, universe, demo_provider,
                        technical=technical, political=political,
                    )
                )
                if evaluation.setup_present:
                    pytest.fail(
                        f"{strategy_id} fired on {ticker} on political evidence "
                        "alone, with every technical confirmation removed"
                    )

    def test_political_confirmation_is_what_unlocks_the_trade(
        self, universe, demo_provider
    ):
        """The mirror of the test above: with confirmation present, the same
        political evidence does produce a setup. Otherwise the gate above would
        pass trivially."""
        from trading_universe.domain.snapshots import PoliticalSnapshot

        now = datetime.now(UTC)
        strategy = build_strategy("congress_fresh_purchase")
        fired = 0
        for ticker in universe.tickers():
            if archetype_for(ticker) != "catalyst_breakout":
                continue
            political = PoliticalSnapshot(
                ticker=ticker, as_of=now, purchases_30d=2,
                distinct_politicians_30d=2, newest_disclosure_age_days=3.0,
                newest_transaction_lag_days=17.0, largest_band_usd=100_000.0,
                consensus_score=0.8, freshness_score=0.9, chambers_30d=["HOUSE"],
            )
            if strategy.evaluate(
                _context(ticker, universe, demo_provider, political=political)
            ).setup_present:
                fired += 1
        assert fired > 0, "political strategies never fire even with confirmation"

    def test_political_strategies_use_the_political_weight(self, universe, demo_provider):
        from trading_universe.domain.enums import StrategyKind

        for strategy_id in (
            "congress_fresh_purchase", "congress_consensus", "congress_repeat_buyer"
        ):
            assert build_strategy(strategy_id).kind is StrategyKind.POLITICAL

    def test_no_committee_weighting_is_applied(self):
        """Spec 15: no extra weight for committee membership without a
        defensible, testable reason."""
        strategy = build_strategy("congress_consensus")
        assert strategy.cfg("political.committee_weighting") is False
