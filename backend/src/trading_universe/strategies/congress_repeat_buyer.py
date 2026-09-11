"""P3 - Repeat High-Conviction Buyer (spec section 16).

Repeated accumulation of the same company by the same disclosed account may
carry more information than one isolated transaction.

The political subscore weights come from the spec:
    30% recency + 25% repeat frequency + 20% size + 15% no recent sales
    + 10% historical follow-through
Follow-through stays neutral until enough post-disclosure return history has
accumulated - inventing it would be fabricating a track record.
"""

from __future__ import annotations

from trading_universe.strategies.base import StrategyContext, StrategyEvaluation
from trading_universe.strategies.congress_purchase import PoliticalStrategy


class CongressRepeatBuyer(PoliticalStrategy):
    id = "congress_repeat_buyer"
    label = "Repeat High-Conviction Buyer"

    def evaluate(self, ctx: StrategyContext) -> StrategyEvaluation:
        passed: list[str] = []
        failed: list[str] = []
        pol = ctx.political

        if pol is None or not pol.repeat_buyers:
            return self._fail(ctx, ["no disclosed repeat purchases"], passed)

        min_purchases = int(self.cfg("political.min_purchases", 3))
        window = int(self.cfg("political.window_days", 180))
        top_buyer, top_count = next(iter(pol.repeat_buyers.items()))

        if top_count >= min_purchases:
            passed.append(
                f"{top_buyer.split('|')[0]} disclosed {top_count} purchases "
                f"in the last {window} days"
            )
        else:
            failed.append(
                f"top buyer has {top_count} disclosed purchase(s), need {min_purchases}"
            )

        if self.cfg("political.require_no_sales", True):
            if top_buyer in pol.politicians_with_sales:
                failed.append("the repeat buyer has also disclosed sales in the window")
            else:
                passed.append("no disclosed sales by the repeat buyer")

        political_fit = pol.repeat_score
        if political_fit <= 0.0 and not failed:
            failed.append("repeat-buyer score is zero")

        t_pass, t_fail, t_fit = self.check_technical_confirmation(ctx)
        s_ok, s_pass, s_fail, s_fit = self.check_sentiment(ctx)
        f_ok, f_pass, f_fail, f_fit = self.check_fundamentals(ctx)
        passed += t_pass + s_pass + f_pass
        failed += t_fail + s_fail + f_fail

        return self._finish(
            ctx, passed, failed, political_fit, t_fit, s_fit, f_fit,
            evidence={
                "top_buyer": top_buyer,
                "top_buyer_purchases": top_count,
                "repeat_buyers": pol.repeat_buyers,
                "repeat_score": pol.repeat_score,
                "politicians_with_sales": pol.politicians_with_sales,
                "newest_disclosure_age_days": pol.newest_disclosure_age_days,
                "largest_band_usd": pol.largest_band_usd,
                "historical_follow_through": "neutral - insufficient post-disclosure history",
            },
            invalidation_label="technical invalidation",
        )
