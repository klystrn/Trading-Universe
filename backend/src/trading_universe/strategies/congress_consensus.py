"""P2 - Congressional Consensus (spec section 15).

Multiple independent politicians disclosing purchases in the same company is a
stronger public-disclosure signal than one isolated purchase.

Note what is deliberately absent: no extra weight for committee membership. The
spec requires a defensible, testable reason before such a weighting is added,
and there isn't one yet.
"""

from __future__ import annotations

from trading_universe.strategies.congress_purchase import PoliticalStrategy
from trading_universe.strategies.base import StrategyContext, StrategyEvaluation


class CongressConsensus(PoliticalStrategy):
    id = "congress_consensus"
    label = "Congressional Consensus"

    def evaluate(self, ctx: StrategyContext) -> StrategyEvaluation:
        passed: list[str] = []
        failed: list[str] = []
        pol = ctx.political

        if pol is None or pol.purchases_30d == 0:
            return self._fail(ctx, ["no disclosed congressional purchases"], passed)

        min_politicians = int(self.cfg("political.min_distinct_politicians", 2))
        window = int(self.cfg("political.window_days", 30))

        if pol.distinct_politicians_30d >= min_politicians:
            passed.append(
                f"{pol.distinct_politicians_30d} independent politicians disclosed "
                f"purchases in the last {window} days"
            )
        else:
            failed.append(
                f"only {pol.distinct_politicians_30d} distinct buyer(s), "
                f"need {min_politicians}"
            )

        if len(pol.chambers_30d) > 1:
            passed.append("both chambers represented")

        if self.cfg("political.net_purchase_required", True):
            if pol.purchases_30d > pol.sales_30d:
                passed.append(
                    f"net buying ({pol.purchases_30d} purchases vs {pol.sales_30d} sales)"
                )
            else:
                failed.append(
                    f"not net buying ({pol.purchases_30d} purchases vs {pol.sales_30d} sales)"
                )

        political_fit = pol.consensus_score
        if political_fit <= 0.0 and not failed:
            failed.append("consensus score is zero")

        t_pass, t_fail, t_fit = self.check_technical_confirmation(ctx)
        s_ok, s_pass, s_fail, s_fit = self.check_sentiment(ctx)
        f_ok, f_pass, f_fail, f_fit = self.check_fundamentals(ctx)
        passed += t_pass + s_pass + f_pass
        failed += t_fail + s_fail + f_fail

        return self._finish(
            ctx, passed, failed, political_fit, t_fit, s_fit, f_fit,
            evidence={
                "distinct_politicians_30d": pol.distinct_politicians_30d,
                "purchases_30d": pol.purchases_30d,
                "sales_30d": pol.sales_30d,
                "chambers": pol.chambers_30d,
                "consensus_score": pol.consensus_score,
                "total_amount_low_30d": pol.total_amount_low_30d,
                "total_amount_high_30d": pol.total_amount_high_30d,
                "newest_disclosure_age_days": pol.newest_disclosure_age_days,
                "committee_weighting_applied": False,
            },
            invalidation_label="technical invalidation",
        )
