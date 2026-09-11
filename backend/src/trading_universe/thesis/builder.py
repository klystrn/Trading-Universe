"""Build the machine-readable trade thesis (spec section 21).

Every signal produces one, accepted or not. Rejected theses are the dataset that
later answers "did the setups we turned down do better than the ones we took?",
so they are recorded with the same fidelity as accepted ones.
"""

from __future__ import annotations

from trading_universe.domain.signals import Signal
from trading_universe.domain.thesis import TradeThesis

# Evidence keys routed into each thesis section. Anything unrecognised lands in
# ``technical`` rather than being dropped.
_SENTIMENT_KEYS = {
    "sentiment_trend", "sentiment_improvement", "catalyst_type", "catalyst_strength",
    "catalyst_sessions_ago", "sentiment_fit",
}
_FUNDAMENTAL_KEYS = {
    "quality_score", "value_percentile", "fcf_yield", "revenue_yoy",
    "operating_margin_change", "free_cash_flow_positive", "debt_trend",
    "fundamental_fit",
}
_POLITICAL_KEYS = {
    "purchases_30d", "sales_30d", "distinct_politicians_30d", "chambers",
    "consensus_score", "repeat_score", "freshness_score", "repeat_buyers",
    "top_buyer", "top_buyer_purchases", "politicians_with_sales",
    "newest_disclosure_age_days", "disclosure_lag_days", "largest_band_usd",
    "total_amount_low_30d", "total_amount_high_30d", "political_fit",
    "committee_weighting_applied", "historical_follow_through",
}
_TARGET_KEYS = {
    "minimum_target", "minimum_rr", "selected_rr", "resistance",
    "resistance_below_minimum_target", "holding_period_days",
}


def build_thesis(signal: Signal, accepted: bool) -> TradeThesis:
    technical: dict[str, object] = {}
    sentiment: dict[str, object] = {}
    fundamentals: dict[str, object] = {}
    political: dict[str, object] = {}
    market: dict[str, object] = {
        "regime": signal.market.regime.value,
        "sector_regime": signal.market.sector_regime.value,
        "strategy_match": signal.market.strategy_match,
        "sector": signal.sector,
        "subsector": signal.subsector,
    }

    for key, value in signal.evidence.items():
        if key in _SENTIMENT_KEYS:
            sentiment[key] = value
        elif key in _FUNDAMENTAL_KEYS:
            fundamentals[key] = value
        elif key in _POLITICAL_KEYS:
            political[key] = value
        elif key in _TARGET_KEYS:
            market[key] = value
        else:
            technical[key] = value

    return TradeThesis(
        # Until a broker fills it, the thesis is identified by its signal.
        trade_id=f"{signal.generated_at:%Y%m%d}-{signal.ticker}-{signal.signal_id[:8]}",
        signal_id=signal.signal_id,
        ticker=signal.ticker,
        strategy=signal.strategy_id,
        side=signal.side,
        signal_score=signal.score.total,
        technical_score=signal.score.technical,
        sentiment_score=signal.score.sentiment,
        fundamental_score=signal.score.fundamental,
        political_score=signal.score.political,
        entry=signal.trade.entry,
        stop=signal.trade.stop,
        target=signal.trade.target,
        reward_risk=signal.trade.reward_risk,
        max_position_value=signal.trade.max_position_value,
        technical=technical,
        sentiment=sentiment,
        fundamentals=fundamentals,
        political=political or None,
        market=market,
        freshness=signal.freshness.model_dump(mode="json"),
        invalidation=signal.invalidation,
        generated_at=signal.generated_at,
        accepted=accepted,
        rejection_reasons=list(signal.execution.reasons),
    )
