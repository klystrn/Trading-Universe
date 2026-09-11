"""Signal scoring (spec section 8).

Weights live in ``config/strategies.yaml``, not here, so the same rubric applies
to every strategy and the UI sliders map onto one place.

    Standard:  technical 40 + sentiment 30 + fundamental 30 = 100, execute >= 70
    Political: political 25 + technical 30 + sentiment 20 + fundamental 25, >= 75

A strategy supplies sub-factor fits on 0-1; this layer multiplies by the weights.
"""

from __future__ import annotations

from datetime import UTC, datetime

from trading_universe.config import get_config
from trading_universe.data.freshness import FreshnessService
from trading_universe.domain.enums import FreshnessStatus, OrderSide, StrategyKind
from trading_universe.domain.signals import (
    MarketContext,
    Signal,
    SignalFreshness,
    SignalScore,
    TradeParams,
)
from trading_universe.strategies.base import Strategy, StrategyContext, StrategyProposal


class SignalScorer:
    """Turns a :class:`StrategyProposal` into a scored :class:`Signal`."""

    def __init__(self, freshness: FreshnessService | None = None) -> None:
        self.freshness = freshness

    # -- scoring ------------------------------------------------------------
    def score(self, proposal: StrategyProposal) -> SignalScore:
        weights = get_config().strategies.weights(proposal.kind.value)

        if proposal.kind is StrategyKind.POLITICAL:
            political_weight = float(weights.get("political", 25))
            return SignalScore(
                technical=round(proposal.technical_fit * float(weights.get("technical", 30)), 2),
                sentiment=round(proposal.sentiment_fit * float(weights.get("sentiment", 20)), 2),
                fundamental=round(
                    proposal.fundamental_fit * float(weights.get("fundamental", 25)), 2
                ),
                political=round((proposal.political_fit or 0.0) * political_weight, 2),
            )

        return SignalScore(
            technical=round(proposal.technical_fit * float(weights.get("technical", 40)), 2),
            sentiment=round(proposal.sentiment_fit * float(weights.get("sentiment", 30)), 2),
            fundamental=round(
                proposal.fundamental_fit * float(weights.get("fundamental", 30)), 2
            ),
            political=None,
        )

    def minimum_score(self, strategy_id: str) -> float:
        return get_config().strategies.minimum_score(strategy_id)

    # -- signal construction -------------------------------------------------
    def build_signal(
        self,
        proposal: StrategyProposal,
        ctx: StrategyContext,
        strategy: Strategy,
        now: datetime | None = None,
    ) -> Signal:
        now = now or datetime.now(UTC)
        score = self.score(proposal)

        trade = TradeParams(
            entry=proposal.entry,
            stop=proposal.stop,
            target=proposal.target,
            max_position_value=get_config().risk.max_position_value,
        )

        market = MarketContext(
            regime=ctx.regime.regime if ctx.regime else MarketContext().regime,
            sector_regime=(
                ctx.sector_regime.regime if ctx.sector_regime else MarketContext().sector_regime
            ),
            strategy_match=strategy.regime_match(ctx),
        )

        return Signal(
            ticker=proposal.ticker,
            strategy_id=proposal.strategy_id,
            strategy_kind=proposal.kind,
            sector=ctx.stock.sector,
            subsector=ctx.stock.subsector,
            direction=OrderSide.BUY,
            generated_at=now,
            score=score,
            trade=trade,
            market=market,
            freshness=self._freshness_for(proposal.strategy_id, now),
            evidence={
                **proposal.evidence,
                "holding_period_days": list(proposal.holding_period_days),
                "technical_fit": proposal.technical_fit,
                "sentiment_fit": proposal.sentiment_fit,
                "fundamental_fit": proposal.fundamental_fit,
                "political_fit": proposal.political_fit,
            },
            invalidation=proposal.invalidation,
        )

    def _freshness_for(self, strategy_id: str, now: datetime) -> SignalFreshness:
        if self.freshness is None:
            return SignalFreshness()
        _, _, states = self.freshness.evaluate_strategy(strategy_id, now)

        def pick(*names: str) -> FreshnessStatus:
            found = [states[n].status for n in names if n in states]
            if not found:
                return FreshnessStatus.UNAVAILABLE
            # Worst status wins - the weakest source defines what we can trust.
            order = [
                FreshnessStatus.LIVE,
                FreshnessStatus.HEALTHY,
                FreshnessStatus.DEGRADED,
                FreshnessStatus.STALE,
                FreshnessStatus.UNAVAILABLE,
            ]
            return max(found, key=order.index)

        political = (
            pick("political_disclosure") if "political_disclosure" in states else None
        )
        return SignalFreshness(
            market_data=pick("quote_active_candidate", "candle_daily"),
            news=pick("news_sentiment_aggregate", "news_discovery"),
            fundamentals=pick("fundamental_ratios", "sec_filing"),
            political=political,
            details={
                name: state.age_seconds
                for name, state in states.items()
                if state.age_seconds is not None
            },
        )
