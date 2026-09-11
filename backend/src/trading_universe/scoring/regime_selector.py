"""Daily strategy recommendation (spec sections 6, 67, 68).

Trading Universe does not assume one strategy is best every day. Each trading day
the selector assesses the regime and recommends one primary strategy plus
sector-specific preferences.

Two concepts stay separate:

* **Recommended strategy** - produced here, automatically.
* **Active execution strategy** - chosen by the user accepting the recommendation
  or overriding it. Only the active strategy may execute automatically; every
  other strategy keeps scanning and keeps appearing in the scanner and the
  universe (spec 67).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from trading_universe.config import get_config
from trading_universe.domain.enums import MarketRegime
from trading_universe.domain.regime import (
    RegimeSnapshot,
    SectorRegime,
    StrategyRecommendation,
)
from trading_universe.strategies.registry import STRATEGY_BY_ID, strategy_labels

# How well each strategy suits each regime, 0-1. Derived from the spec's
# regime -> preferred strategy table, with non-preferred strategies given a
# non-zero floor because they keep scanning regardless.
_BASE_FIT: dict[MarketRegime, dict[str, float]] = {
    MarketRegime.STRONG_BULL: {
        "quality_momentum_pullback": 1.00,
        "quality_volatility_squeeze": 0.85,
        "fundamental_catalyst_breakout": 0.65,
        "value_rerating_50dma_reclaim": 0.40,
        "quality_oversold_reversal": 0.25,
    },
    MarketRegime.BULL: {
        "quality_momentum_pullback": 1.00,
        "fundamental_catalyst_breakout": 0.85,
        "quality_volatility_squeeze": 0.65,
        "value_rerating_50dma_reclaim": 0.50,
        "quality_oversold_reversal": 0.35,
    },
    MarketRegime.NEUTRAL: {
        "quality_volatility_squeeze": 1.00,
        "value_rerating_50dma_reclaim": 0.85,
        "quality_momentum_pullback": 0.60,
        "fundamental_catalyst_breakout": 0.55,
        "quality_oversold_reversal": 0.45,
    },
    MarketRegime.HIGH_VOLATILITY: {
        "fundamental_catalyst_breakout": 1.00,
        "quality_oversold_reversal": 0.85,
        "quality_volatility_squeeze": 0.35,
        "quality_momentum_pullback": 0.30,
        "value_rerating_50dma_reclaim": 0.30,
    },
    MarketRegime.CORRECTION: {
        "quality_oversold_reversal": 1.00,
        "congress_consensus": 0.60,
        "value_rerating_50dma_reclaim": 0.40,
        "fundamental_catalyst_breakout": 0.25,
        "quality_momentum_pullback": 0.15,
        "quality_volatility_squeeze": 0.15,
    },
    MarketRegime.RECOVERY: {
        "quality_oversold_reversal": 1.00,
        "value_rerating_50dma_reclaim": 0.90,
        "quality_momentum_pullback": 0.55,
        "fundamental_catalyst_breakout": 0.50,
        "quality_volatility_squeeze": 0.45,
    },
    # Mostly cash, extremely selective: nothing scores well.
    MarketRegime.RISK_OFF: {
        "quality_oversold_reversal": 0.30,
        "congress_consensus": 0.25,
        "value_rerating_50dma_reclaim": 0.20,
    },
}

_POLITICAL_FLOOR = 0.45  # political strategies are largely regime-independent


class RegimeSelector:
    """Recommends the strategy of the day and per-sector preferences."""

    def __init__(self) -> None:
        self.labels = strategy_labels()

    # -- fit ----------------------------------------------------------------
    def strategy_fit(self, strategy_id: str, regime: MarketRegime) -> float:
        table = _BASE_FIT.get(regime, {})
        if strategy_id in table:
            return table[strategy_id]
        if strategy_id.startswith("congress_"):
            # Political signals depend on disclosures, not on the tape, but a
            # risk-off tape still argues for restraint.
            return 0.15 if regime is MarketRegime.RISK_OFF else _POLITICAL_FLOOR
        return 0.20

    def rank(
        self,
        regime: MarketRegime,
        recent_performance: dict[str, float] | None = None,
        signal_counts: dict[str, int] | None = None,
    ) -> list[tuple[str, float]]:
        """Rank enabled strategies for a regime.

        ``recent_performance`` (average R per strategy, from analytics) nudges
        the ranking once real history exists. It is a tilt, never an override:
        the rule-based fit stays dominant so the recommendation remains
        explainable (spec 7, 71).
        """
        cfg = get_config().strategies
        enabled = set(cfg.enabled_strategies())
        recent_performance = recent_performance or {}
        signal_counts = signal_counts or {}

        scored: list[tuple[str, float]] = []
        for sid in STRATEGY_BY_ID:
            if sid not in enabled:
                continue
            fit = self.strategy_fit(sid, regime)

            # Performance tilt: +/-0.12 at most.
            avg_r = recent_performance.get(sid)
            if avg_r is not None:
                fit += max(-0.12, min(0.12, avg_r * 0.12))

            # A strategy with nothing to trade today cannot be the strategy of
            # the day, however well it fits in theory.
            count = signal_counts.get(sid)
            if count is not None:
                if count == 0:
                    fit *= 0.35
                elif count < 3:
                    fit *= 0.85

            scored.append((sid, round(max(0.0, min(1.0, fit)), 4)))

        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored

    # -- sector recommendations ---------------------------------------------
    def recommend_for_sector(
        self, sector: SectorRegime, signal_counts_by_strategy: dict[str, int] | None = None
    ) -> SectorRegime:
        ranked = self.rank(sector.regime, signal_counts=signal_counts_by_strategy)
        if not ranked:
            sector.recommended_strategy = None
            sector.confidence = 0.0
            return sector

        # A sector with disclosed political accumulation gets political
        # strategies promoted, matching the spec's Industrials example.
        if sector.political_activity >= 2:
            political = [r for r in ranked if r[0].startswith("congress_")]
            if political and political[0][1] >= 0.35:
                best_political = max(political, key=lambda r: r[1])
                if best_political[1] + 0.15 >= ranked[0][1]:
                    ranked = [best_political] + [r for r in ranked if r[0] != best_political[0]]

        sector.recommended_strategy = ranked[0][0]
        # Blend strategy fit with how convinced we are of the sector's regime.
        regime_conviction = 0.5 + 0.5 * min(1.0, abs(sector.relative_strength) / 0.03)
        sector.confidence = round(min(1.0, 0.65 * ranked[0][1] + 0.35 * regime_conviction), 4)
        return sector

    # -- the daily recommendation -------------------------------------------
    def recommend(
        self,
        market: RegimeSnapshot,
        sectors: list[SectorRegime],
        signal_counts_by_strategy: dict[str, int] | None = None,
        recent_performance: dict[str, float] | None = None,
        trading_day: date | None = None,
        now: datetime | None = None,
    ) -> StrategyRecommendation:
        now = now or datetime.now(UTC)
        trading_day = trading_day or now.date()

        ranked = self.rank(
            market.regime,
            recent_performance=recent_performance,
            signal_counts=signal_counts_by_strategy,
        )
        sector_recs = [
            self.recommend_for_sector(s, signal_counts_by_strategy) for s in sectors
        ]

        if not ranked:
            # RISK_OFF with everything filtered out is a legitimate answer.
            return StrategyRecommendation(
                trading_day=trading_day,
                generated_at=now,
                primary_strategy="NO_TRADE",
                confidence=market.confidence,
                market_regime=market.regime,
                rationale=market.rationale + ["no strategy fits the current regime"],
                sector_recommendations=sector_recs,
            )

        primary, fit = ranked[0]
        confidence = round(min(1.0, 0.7 * fit + 0.3 * market.confidence), 4)

        rationale = list(market.rationale)
        rationale.append(
            f"{self.labels.get(primary, primary)} fits a "
            f"{market.regime.value.replace('_', ' ').lower()} regime best ({fit:.0%})"
        )
        if signal_counts_by_strategy:
            count = signal_counts_by_strategy.get(primary, 0)
            rationale.append(f"{count} qualifying setup(s) found today")
        leaders = [s.sector_id for s in sector_recs[:2]]
        if leaders:
            rationale.append("sector leadership: " + ", ".join(leaders))

        return StrategyRecommendation(
            trading_day=trading_day,
            generated_at=now,
            primary_strategy=primary,
            confidence=confidence,
            market_regime=market.regime,
            rationale=rationale,
            sector_recommendations=sector_recs,
            alternatives=ranked[1:5],
        )
