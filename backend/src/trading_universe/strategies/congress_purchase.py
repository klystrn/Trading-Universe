"""P1 - Fresh Congressional Purchase + Confirmation (spec section 14).

A newly disclosed political purchase identifies an interesting candidate. It
must never trigger execution on its own. This is a signal generator, not a
copy-trading instruction, so the disclosure only opens the door: fundamentals,
sentiment and a current technical confirmation still have to agree.
"""

from __future__ import annotations

from trading_universe.domain.enums import StrategyKind
from trading_universe.features.political import fresh_purchase_score
from trading_universe.strategies.base import (
    Strategy,
    StrategyContext,
    StrategyEvaluation,
    StrategyProposal,
)


class PoliticalStrategy(Strategy):
    """Shared plumbing for the three political strategies."""

    kind = StrategyKind.POLITICAL

    def _amount_curve(self) -> dict[int, float] | None:
        curve = self.cfg("political.amount_band_score_curve")
        if not curve:
            return None
        return {int(k): float(v) for k, v in curve.items()}

    def check_technical_confirmation(
        self, ctx: StrategyContext
    ) -> tuple[list[str], list[str], float]:
        """Above the 50DMA, or reclaiming it, plus a current entry trigger."""
        tech = ctx.technical
        passed: list[str] = []
        failed: list[str] = []

        if self.cfg("technical.require_above_or_reclaiming_50dma", True):
            if tech.price_above_50dma:
                passed.append("price above the 50DMA")
            elif tech.reclaimed_50dma:
                passed.append("reclaiming the 50DMA")
            else:
                failed.append("price below the 50DMA with no reclaim")

        lookback = int(self.cfg("technical.breakout_lookback", 10))
        recent_high = (
            max(c.high for c in ctx.candles[-(lookback + 1) : -1])
            if len(ctx.candles) > lookback
            else tech.high_20
        )
        broke = bool(recent_high and tech.close > recent_high)
        retest = bool(
            recent_high and tech.close >= recent_high * 0.98 and tech.rsi_turning_up
        )
        if broke:
            passed.append(f"broke above the {lookback}-day high")
        elif retest:
            passed.append("holding a retest of the recent high with RSI turning up")
        else:
            failed.append("no current technical entry trigger (breakout or retest)")

        fit = 0.0
        fit += 0.30 if tech.price_above_50dma else (0.18 if tech.reclaimed_50dma else 0.0)
        fit += 0.25 if broke else (0.15 if retest else 0.0)
        fit += 0.20 if tech.price_above_200dma else 0.0
        fit += 0.15 * min(1.0, max(0.0, (tech.volume_ratio - 0.9) / 1.0))
        if tech.rsi14 is not None:
            fit += 0.10 * max(0.0, min(1.0, (tech.rsi14 - 40.0) / 25.0))
        return passed, failed, round(min(1.0, fit), 4)

    def _finish(
        self,
        ctx: StrategyContext,
        passed: list[str],
        failed: list[str],
        political_fit: float,
        tech_fit: float,
        s_fit: float,
        f_fit: float,
        evidence: dict,
        invalidation_label: str,
    ) -> StrategyEvaluation:
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
                invalidation=f"{invalidation_label}, below {stop:.2f}",
                technical_fit=tech_fit,
                sentiment_fit=s_fit,
                fundamental_fit=f_fit,
                political_fit=political_fit,
                holding_period_days=self.holding_period,
                evidence={**evidence, **target_notes},
            ),
        )


class CongressFreshPurchase(PoliticalStrategy):
    id = "congress_fresh_purchase"
    label = "Fresh Congressional Purchase"

    def evaluate(self, ctx: StrategyContext) -> StrategyEvaluation:
        passed: list[str] = []
        failed: list[str] = []
        pol = ctx.political

        if pol is None or pol.purchases_30d == 0:
            return self._fail(ctx, ["no disclosed congressional purchase"], passed)

        max_age = int(self.cfg("political.max_disclosure_age_days", 21))
        min_amount = float(self.cfg("political.min_amount_band_usd", 15000))

        age = pol.newest_disclosure_age_days
        if age is None:
            failed.append("disclosure date unavailable")
        elif age <= max_age:
            passed.append(
                f"disclosed {age:.0f} day(s) ago "
                f"(reporting lag {pol.newest_transaction_lag_days:.0f} days)"
            )
        else:
            failed.append(f"newest disclosure {age:.0f} days old, older than {max_age}")

        if pol.largest_band_usd >= min_amount:
            passed.append(
                f"largest disclosed band ${pol.largest_band_usd:,.0f}"
            )
        else:
            failed.append(
                f"largest band ${pol.largest_band_usd:,.0f} below the ${min_amount:,.0f} floor"
            )

        political_fit = fresh_purchase_score(
            pol, max_age_days=max_age, min_amount=min_amount, amount_curve=self._amount_curve()
        )
        if political_fit <= 0.0 and not failed:
            failed.append("political signal too weak to act on")

        t_pass, t_fail, t_fit = self.check_technical_confirmation(ctx)
        s_ok, s_pass, s_fail, s_fit = self.check_sentiment(ctx)
        f_ok, f_pass, f_fail, f_fit = self.check_fundamentals(ctx)
        passed += t_pass + s_pass + f_pass
        failed += t_fail + s_fail + f_fail

        return self._finish(
            ctx, passed, failed, political_fit, t_fit, s_fit, f_fit,
            evidence={
                "purchases_30d": pol.purchases_30d,
                "distinct_politicians_30d": pol.distinct_politicians_30d,
                "newest_disclosure_age_days": pol.newest_disclosure_age_days,
                "disclosure_lag_days": pol.newest_transaction_lag_days,
                "largest_band_usd": pol.largest_band_usd,
                "chambers": pol.chambers_30d,
                "freshness_score": pol.freshness_score,
            },
            invalidation_label="technical invalidation",
        )
