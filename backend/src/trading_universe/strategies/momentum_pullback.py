"""S1 - Quality Momentum Pullback (spec section 9).

Buy fundamentally strong companies in established uptrends after controlled
pullbacks, only once buyers begin returning. The last clause is what separates
this from catching a falling knife: an untriggered pullback is not a trade.
"""

from __future__ import annotations

from trading_universe.domain.enums import StrategyKind
from trading_universe.strategies.base import (
    Strategy,
    StrategyContext,
    StrategyEvaluation,
    StrategyProposal,
)


class QualityMomentumPullback(Strategy):
    id = "quality_momentum_pullback"
    label = "Quality Momentum Pullback"
    kind = StrategyKind.STANDARD

    def evaluate(self, ctx: StrategyContext) -> StrategyEvaluation:
        tech = ctx.technical
        passed: list[str] = []
        failed: list[str] = []

        if tech.bars_available < 200:
            return self._fail(ctx, ["insufficient history for a 200DMA"], passed)

        # --- long-term trend: price > 50DMA > 200DMA -----------------------
        if self.cfg("trend.require_price_above_50dma", True):
            if tech.price_above_50dma:
                passed.append("price above the 50DMA")
            else:
                failed.append("price below the 50DMA")
        if self.cfg("trend.require_50dma_above_200dma", True):
            if tech.dma50_above_dma200:
                passed.append("50DMA above the 200DMA")
            else:
                failed.append("50DMA below the 200DMA")

        # --- the pullback itself -------------------------------------------
        ema_tol = float(self.cfg("pullback.ema20_distance_pct", 2.0)) / 100.0
        dma_tol = float(self.cfg("pullback.dma50_distance_pct", 2.5)) / 100.0
        at_ema20 = bool(tech.ema20 and abs(tech.close - tech.ema20) / tech.ema20 <= ema_tol)
        at_dma50 = bool(
            self.cfg("pullback.allow_50dma_pullback", True)
            and tech.dma50
            and abs(tech.close - tech.dma50) / tech.dma50 <= dma_tol
        )
        if at_ema20 or at_dma50:
            passed.append("price pulled back to the " + ("20EMA" if at_ema20 else "50DMA"))
        else:
            failed.append("price is not at a pullback level (20EMA / 50DMA)")

        # A pullback that has become a decline is a different situation.
        max_dd = float(self.cfg("pullback.max_drawdown_from_20d_high_pct", 12.0)) / 100.0
        if tech.pct_from_20d_high is not None:
            if tech.pct_from_20d_high >= -max_dd:
                passed.append(f"{tech.pct_from_20d_high:+.1%} from the 20-day high")
            else:
                failed.append(
                    f"drawdown {tech.pct_from_20d_high:+.1%} exceeds the "
                    f"{max_dd:.0%} pullback limit - this is a decline, not a pullback"
                )

        # --- RSI in the band, and turning up --------------------------------
        rsi_min = float(self.cfg("rsi.min", 40.0))
        rsi_max = float(self.cfg("rsi.max", 60.0))
        if tech.rsi14 is None:
            failed.append("RSI unavailable")
        elif rsi_min <= tech.rsi14 <= rsi_max:
            passed.append(f"RSI {tech.rsi14:.0f} inside the {rsi_min:.0f}-{rsi_max:.0f} band")
        else:
            failed.append(f"RSI {tech.rsi14:.0f} outside the {rsi_min:.0f}-{rsi_max:.0f} band")

        if self.cfg("rsi.require_rising", True):
            if tech.rsi_turning_up:
                passed.append(
                    f"RSI rising ({(tech.rsi14_prev or 0):.0f} -> {(tech.rsi14 or 0):.0f})"
                )
            else:
                failed.append("RSI still falling - buyers have not returned yet")

        # --- confirmation: buyers actually returning -------------------------
        if self.cfg("confirmation.require_vwap_or_prior_high", True):
            prior_high = ctx.candles[-2].high if len(ctx.candles) >= 2 else None
            reclaimed_prior = bool(prior_high and tech.close > prior_high)
            if tech.vwap_reclaimed or reclaimed_prior:
                passed.append(
                    "reclaimed VWAP" if tech.vwap_reclaimed else "cleared the prior bar's high"
                )
            else:
                failed.append("no momentum confirmation (VWAP or prior-bar high)")

        min_vol = float(self.cfg("confirmation.min_volume_ratio", 1.0))
        if tech.volume_ratio >= min_vol:
            passed.append(f"rebound volume {tech.volume_ratio:.2f}x the 20-day average")
        else:
            failed.append(f"rebound volume {tech.volume_ratio:.2f}x below {min_vol:.2f}x")

        # --- sentiment and fundamentals --------------------------------------
        s_ok, s_pass, s_fail, s_fit = self.check_sentiment(ctx)
        f_ok, f_pass, f_fail, f_fit = self.check_fundamentals(ctx)
        passed += s_pass + f_pass
        failed += s_fail + f_fail

        if failed:
            return self._fail(ctx, failed, passed)

        # --- geometry ---------------------------------------------------------
        entry = ctx.price
        stop = self.place_stop(ctx)
        if stop is None or stop >= entry:
            return self._fail(ctx, ["no valid technical invalidation level"], passed)
        target, target_notes = self.build_target(entry, stop, self.resistance_for(ctx))

        technical_fit = self._technical_fit(ctx, at_ema20)

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
                invalidation=f"break below {stop:.2f}",
                technical_fit=technical_fit,
                sentiment_fit=s_fit,
                fundamental_fit=f_fit,
                holding_period_days=self.holding_period,
                evidence={
                    "price_above_200dma": tech.price_above_200dma,
                    "price_above_50dma": tech.price_above_50dma,
                    "dma50_above_dma200": tech.dma50_above_dma200,
                    "ema20_pullback": at_ema20,
                    "dma50_pullback": at_dma50,
                    "rsi14": tech.rsi14,
                    "rsi14_prev": tech.rsi14_prev,
                    "volume_ratio": tech.volume_ratio,
                    "vwap_reclaimed": tech.vwap_reclaimed,
                    "pct_from_20d_high": tech.pct_from_20d_high,
                    "atr14": tech.atr14,
                    **target_notes,
                },
            ),
        )

    def _technical_fit(self, ctx: StrategyContext, at_ema20: bool) -> float:
        """How textbook is this pullback? 0-1."""
        tech = ctx.technical
        score = 0.0
        # Trend structure is the foundation: half the weight.
        score += 0.25 if tech.price_above_50dma else 0.0
        score += 0.15 if tech.dma50_above_dma200 else 0.0
        score += 0.10 if tech.price_above_200dma else 0.0
        # Pullback quality: the 20EMA is the cleaner of the two levels.
        score += 0.12 if at_ema20 else 0.07
        # RSI closest to the middle of the band is the cleanest reset.
        if tech.rsi14 is not None:
            centre = (float(self.cfg("rsi.min", 40)) + float(self.cfg("rsi.max", 60))) / 2.0
            half = (float(self.cfg("rsi.max", 60)) - float(self.cfg("rsi.min", 40))) / 2.0
            score += 0.13 * max(0.0, 1.0 - abs(tech.rsi14 - centre) / max(half, 1e-6))
        # Confirmation strength.
        score += 0.10 if tech.vwap_reclaimed else 0.0
        score += 0.15 * min(1.0, max(0.0, (tech.volume_ratio - 0.8) / 0.9))
        return round(min(1.0, score), 4)
