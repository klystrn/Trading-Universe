"""S4 - Quality Volatility Squeeze (spec section 12).

Volatility compression can precede expansion. Trade the breakout only when
fundamentals and sentiment are acceptable - a squeeze in a broken company
resolves downward just as readily.
"""

from __future__ import annotations

from trading_universe.domain.enums import StrategyKind
from trading_universe.strategies.base import (
    Strategy,
    StrategyContext,
    StrategyEvaluation,
    StrategyProposal,
)


class QualityVolatilitySqueeze(Strategy):
    id = "quality_volatility_squeeze"
    label = "Quality Volatility Squeeze"
    kind = StrategyKind.STANDARD

    def evaluate(self, ctx: StrategyContext) -> StrategyEvaluation:
        tech = ctx.technical
        passed: list[str] = []
        failed: list[str] = []

        if tech.bars_available < 90:
            return self._fail(ctx, ["insufficient history for a 3-month width comparison"], passed)

        # --- the squeeze ------------------------------------------------------
        # Measured on the bar BEFORE the trigger: once a squeeze fires, its bands
        # have already widened, so the current width no longer shows compression.
        max_pct = float(self.cfg("squeeze.bb_width_percentile_max", 15.0))
        width_pct = tech.bb_width_percentile_prev
        if width_pct is None:
            failed.append("Bollinger width percentile unavailable")
        elif width_pct <= max_pct:
            passed.append(
                f"Bollinger width in the {width_pct:.0f}th percentile of its 3-month range"
            )
        else:
            failed.append(
                f"Bollinger width at the {width_pct:.0f}th percentile - no compression "
                f"(need <= {max_pct:.0f})"
            )

        if self.cfg("squeeze.require_atr_contracting", True):
            if tech.atr_contracting:
                passed.append("ATR contracting")
            else:
                failed.append("ATR not contracting")

        if self.cfg("squeeze.require_volume_declining", True):
            if tech.volume_declining:
                passed.append("volume declining through the consolidation")
            else:
                failed.append("volume not declining through the consolidation")

        # --- trend ---------------------------------------------------------------
        if self.cfg("trend.require_price_above_50dma", True):
            if tech.price_above_50dma:
                passed.append("price above the 50DMA")
            else:
                failed.append("price below the 50DMA")

        # --- the trigger ----------------------------------------------------------
        min_vol = float(self.cfg("trigger.min_volume_ratio", 1.4))
        breakout_lookback = int(self.cfg("trigger.breakout_lookback", 10))
        recent_high = (
            max(c.high for c in ctx.candles[-(breakout_lookback + 1) : -1])
            if len(ctx.candles) > breakout_lookback
            else tech.high_20
        )
        broke_out = bool(recent_high and tech.close > recent_high)
        if broke_out:
            passed.append(f"broke above the {breakout_lookback}-day high")
        else:
            failed.append(f"no expansion above the {breakout_lookback}-day high yet")

        if tech.volume_ratio >= min_vol:
            passed.append(f"expansion volume {tech.volume_ratio:.2f}x the 20-day average")
        else:
            failed.append(f"expansion volume {tech.volume_ratio:.2f}x below {min_vol:.2f}x")

        # --- sentiment and fundamentals ---------------------------------------------
        s_ok, s_pass, s_fail, s_fit = self.check_sentiment(ctx)
        f_ok, f_pass, f_fail, f_fit = self.check_fundamentals(ctx)
        passed += s_pass + f_pass
        failed += s_fail + f_fail

        if failed:
            return self._fail(ctx, failed, passed)

        entry = ctx.price
        stop = self.place_stop(ctx, method=str(self.cfg("stop.method", "structure")))
        if stop is None or stop >= entry:
            return self._fail(ctx, ["no valid consolidation floor for a stop"], passed)
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
                invalidation=f"loss of the consolidation, below {stop:.2f}",
                technical_fit=self._technical_fit(ctx, width_pct),
                sentiment_fit=s_fit,
                fundamental_fit=f_fit,
                holding_period_days=self.holding_period,
                evidence={
                    "bb_width_percentile_pre_trigger": width_pct,
                    "bb_width_percentile_now": tech.bb_width_percentile,
                    "atr_contracting": tech.atr_contracting,
                    "volume_declining": tech.volume_declining,
                    "volume_ratio": tech.volume_ratio,
                    "breakout_level": recent_high,
                    "price_above_50dma": tech.price_above_50dma,
                    **target_notes,
                },
            ),
        )

    def _technical_fit(self, ctx: StrategyContext, width_pct: float | None) -> float:
        tech = ctx.technical
        score = 0.0
        # Tighter compression is a better setup.
        if width_pct is not None:
            score += 0.30 * max(0.0, 1.0 - width_pct / 20.0)
        score += 0.10 if tech.atr_contracting else 0.0
        score += 0.08 if tech.volume_declining else 0.0
        score += 0.30 * min(1.0, max(0.0, (tech.volume_ratio - 1.0) / 1.5))
        score += 0.12 if tech.price_above_50dma else 0.0
        score += 0.10 if tech.price_above_200dma else 0.0
        return round(min(1.0, score), 4)
