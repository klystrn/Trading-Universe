"""S5 - Value Re-rating / 50DMA Reclaim (spec section 13).

Buy financially attractive companies when market perception begins improving
after weakness. The reclaim is the evidence that perception is actually turning;
cheapness alone is not a catalyst.
"""

from __future__ import annotations

from trading_universe.domain.enums import StrategyKind
from trading_universe.strategies.base import (
    Strategy,
    StrategyContext,
    StrategyEvaluation,
    StrategyProposal,
)


class ValueReratingReclaim(Strategy):
    id = "value_rerating_50dma_reclaim"
    label = "Value Re-rating / 50DMA Reclaim"
    kind = StrategyKind.STANDARD

    def evaluate(self, ctx: StrategyContext) -> StrategyEvaluation:
        tech = ctx.technical
        passed: list[str] = []
        failed: list[str] = []

        if tech.bars_available < 90:
            return self._fail(ctx, ["insufficient history"], passed)

        # --- location: it has actually been out of favour -------------------
        if self.cfg("location.require_recently_below_50dma", True):
            if tech.recently_below_50dma:
                passed.append("traded below the 50DMA within the recent window")
            else:
                failed.append("has not been below the 50DMA - there is nothing to re-rate")

        # --- the trigger -----------------------------------------------------
        if self.cfg("trigger.require_50dma_reclaim", True):
            if tech.reclaimed_50dma:
                passed.append("reclaimed the 50DMA")
            else:
                failed.append("50DMA not reclaimed")

        min_vol = float(self.cfg("trigger.min_volume_ratio", 1.1))
        if tech.volume_ratio >= min_vol:
            passed.append(f"reclaim volume {tech.volume_ratio:.2f}x the 20-day average")
        else:
            failed.append(f"reclaim volume {tech.volume_ratio:.2f}x below {min_vol:.2f}x")

        # --- RSI rising through the midline -----------------------------------
        through = float(self.cfg("rsi.rising_through", 50.0))
        tolerance = float(self.cfg("rsi.tolerance", 8.0))
        if tech.rsi14 is None:
            failed.append("RSI unavailable")
        elif abs(tech.rsi14 - through) <= tolerance and tech.rsi_turning_up:
            passed.append(f"RSI rising through {through:.0f} (now {tech.rsi14:.0f})")
        elif tech.rsi14 > through + tolerance:
            failed.append(f"RSI {tech.rsi14:.0f} already well past the {through:.0f} reclaim")
        else:
            failed.append(f"RSI {tech.rsi14:.0f} not yet rising through {through:.0f}")

        # --- sentiment and fundamentals ----------------------------------------
        s_ok, s_pass, s_fail, s_fit = self.check_sentiment(ctx)
        f_ok, f_pass, f_fail, f_fit = self.check_fundamentals(ctx)
        passed += s_pass + f_pass
        failed += s_fail + f_fail

        if failed:
            return self._fail(ctx, failed, passed)

        entry = ctx.price
        stop = self.place_stop(ctx, method=str(self.cfg("stop.method", "structure")))
        if stop is None or stop >= entry:
            return self._fail(ctx, ["no valid structural invalidation level"], passed)
        target, target_notes = self.build_target(entry, stop, self.resistance_for(ctx))

        return StrategyEvaluation(
            strategy_id=self.id,
            ticker=ctx.ticker,
            setup_present=True,
            passed_checks=passed,
            proposal=StrategyProposal(
                strategy_id=self.id,
                kind=self.kind,
                ticker=ctx.ticker,
                entry=round(entry, 4),
                stop=stop,
                target=target,
                invalidation=f"loss of the reclaimed 50DMA, below {stop:.2f}",
                technical_fit=self._technical_fit(ctx),
                sentiment_fit=s_fit,
                fundamental_fit=f_fit,
                holding_period_days=self.holding_period,
                evidence={
                    "reclaimed_50dma": tech.reclaimed_50dma,
                    "recently_below_50dma": tech.recently_below_50dma,
                    "dma50": tech.dma50,
                    "rsi14": tech.rsi14,
                    "volume_ratio": tech.volume_ratio,
                    "value_percentile": ctx.fundamental.value_percentile,
                    "fcf_yield": ctx.fundamental.fcf_yield,
                    "quality_score": ctx.fundamental.quality_score,
                    "sentiment_improvement": round(
                        ctx.sentiment.score_24h - ctx.sentiment.score_7d, 4
                    ),
                    **target_notes,
                },
            ),
        )

    def _technical_fit(self, ctx: StrategyContext) -> float:
        tech = ctx.technical
        score = 0.0
        score += 0.28 if tech.reclaimed_50dma else 0.0
        score += 0.12 if tech.recently_below_50dma else 0.0
        score += 0.22 * min(1.0, max(0.0, (tech.volume_ratio - 0.9) / 1.0))
        if tech.rsi14 is not None:
            score += 0.18 * max(0.0, 1.0 - abs(tech.rsi14 - 52.0) / 15.0)
        score += 0.10 if tech.price_above_200dma else 0.0
        # Cheapness is part of the technical picture only insofar as it means the
        # re-rating has room; the value gate itself lives in the fundamental fit.
        if ctx.fundamental.value_percentile is not None:
            score += 0.10 * (ctx.fundamental.value_percentile / 100.0)
        return round(min(1.0, score), 4)
