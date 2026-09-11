"""S3 - Quality Oversold Reversal (spec section 11).

Strong businesses can become temporarily oversold. The spec is blunt about the
failure mode: do not buy merely because RSI is 27. Require strong fundamentals,
bad-news intensity declining, support surviving, and buyers actually returning.
"""

from __future__ import annotations

from trading_universe.domain.enums import StrategyKind
from trading_universe.strategies.base import (
    Strategy,
    StrategyContext,
    StrategyEvaluation,
    StrategyProposal,
)


class QualityOversoldReversal(Strategy):
    id = "quality_oversold_reversal"
    label = "Quality Oversold Reversal"
    kind = StrategyKind.STANDARD

    def evaluate(self, ctx: StrategyContext) -> StrategyEvaluation:
        tech = ctx.technical
        passed: list[str] = []
        failed: list[str] = []

        if tech.bars_available < 60:
            return self._fail(ctx, ["insufficient history"], passed)

        # --- oversold, then turning ------------------------------------------
        threshold = float(self.cfg("rsi.oversold_below", 35.0))
        if tech.rsi_recently_oversold:
            passed.append(f"RSI reached oversold (< {threshold:.0f}) in the recent window")
        else:
            failed.append(f"RSI has not been below {threshold:.0f} recently")

        if self.cfg("rsi.require_turning_up", True):
            if tech.rsi_turning_up:
                passed.append(
                    f"RSI turning up ({(tech.rsi14_prev or 0):.0f} -> {(tech.rsi14 or 0):.0f})"
                )
            else:
                failed.append("RSI still falling - selling has not exhausted")

        # --- location: at a level worth defending -----------------------------
        if self.cfg("location.require_near_lower_band_or_support", True):
            band_tol = float(self.cfg("location.lower_band_tolerance_pct", 2.0)) / 100.0
            support_tol = float(self.cfg("location.support_tolerance_pct", 2.5)) / 100.0
            near_band = bool(
                tech.bb_lower and (tech.close - tech.bb_lower) / tech.bb_lower <= band_tol
            )
            near_support = bool(
                tech.low_20 and abs(tech.close - tech.low_20) / tech.low_20 <= support_tol
            )
            if near_band or near_support:
                passed.append(
                    "at the lower Bollinger Band" if near_band else "at recent support"
                )
            else:
                failed.append("not at the lower band or a recognised support level")

        # --- trend preference ---------------------------------------------------
        if self.cfg("trend.require_above_200dma", False) and not tech.price_above_200dma:
            failed.append("price below the 200DMA")
        elif tech.price_above_200dma:
            passed.append("still above the 200DMA - a dislocation, not a breakdown")

        # --- reversal evidence ---------------------------------------------------
        min_patterns = int(self.cfg("reversal.min_patterns", 1))
        accepted = set(self.cfg("reversal.accept_patterns", []) or [])
        found: list[str] = []
        if "HIGHER_LOW" in accepted and tech.higher_low:
            found.append("higher low")
        if "BULLISH_ENGULFING" in accepted and tech.bullish_engulfing:
            found.append("bullish engulfing")
        if "VWAP_RECLAIM" in accepted and tech.vwap_reclaimed:
            found.append("VWAP reclaim")
        if len(found) >= min_patterns:
            passed.append("reversal evidence: " + ", ".join(found))
        else:
            failed.append(
                f"no reversal pattern yet (need {min_patterns}, found {len(found)})"
            )

        # --- volume behaviour ---------------------------------------------------
        if self.cfg("volume.require_selling_volume_declining_or_reversal_expanding", True):
            if tech.volume_declining or tech.volume_ratio >= 1.2:
                passed.append(
                    "selling volume declining"
                    if tech.volume_declining
                    else f"reversal volume expanding ({tech.volume_ratio:.2f}x)"
                )
            else:
                failed.append("selling pressure not abating and no reversal volume")

        # --- sentiment and fundamentals ------------------------------------------
        s_ok, s_pass, s_fail, s_fit = self.check_sentiment(ctx)
        f_ok, f_pass, f_fail, f_fit = self.check_fundamentals(ctx)
        passed += s_pass + f_pass
        failed += s_fail + f_fail

        if failed:
            return self._fail(ctx, failed, passed)

        entry = ctx.price
        stop = self.place_stop(ctx)
        if stop is None or stop >= entry:
            return self._fail(ctx, ["no valid technical invalidation level"], passed)
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
                invalidation=f"break below the reversal low at {stop:.2f}",
                technical_fit=self._technical_fit(ctx, found),
                sentiment_fit=s_fit,
                fundamental_fit=f_fit,
                holding_period_days=self.holding_period,
                evidence={
                    "rsi14": tech.rsi14,
                    "rsi_recently_oversold": tech.rsi_recently_oversold,
                    "near_lower_band": tech.near_lower_band,
                    "price_above_200dma": tech.price_above_200dma,
                    "reversal_patterns": found,
                    "volume_ratio": tech.volume_ratio,
                    "volume_declining": tech.volume_declining,
                    "sentiment_trend": ctx.sentiment.trend,
                    "quality_score": ctx.fundamental.quality_score,
                    **target_notes,
                },
            ),
        )

    def _technical_fit(self, ctx: StrategyContext, patterns: list[str]) -> float:
        tech = ctx.technical
        score = 0.0
        # Deeper oversold gives more room, but only paired with reversal evidence.
        if tech.rsi14 is not None:
            score += 0.22 * max(0.0, min(1.0, (45.0 - tech.rsi14) / 20.0))
        score += 0.10 if tech.rsi_turning_up else 0.0
        score += 0.22 * min(1.0, len(patterns) / 2.0)
        score += 0.14 if tech.near_lower_band else 0.06
        score += 0.16 if tech.price_above_200dma else 0.0
        score += 0.16 * min(1.0, max(0.0, (tech.volume_ratio - 0.7) / 1.0))
        return round(min(1.0, score), 4)
