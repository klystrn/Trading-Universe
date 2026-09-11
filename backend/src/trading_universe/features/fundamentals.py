"""Fundamental features and the 0-100 quality score (spec 9, 13).

The quality score is a transparent weighted rubric, not a model. Each component
maps a raw metric onto 0-1 through an explicit, readable curve so a user can
always answer "why is this a 72?".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from trading_universe.domain.snapshots import FundamentalSnapshot

# component -> weight. Sums to 100.
QUALITY_WEIGHTS: dict[str, float] = {
    "revenue_growth": 20.0,
    "margin_trend": 15.0,
    "free_cash_flow": 20.0,
    "leverage": 15.0,
    "returns": 15.0,
    "dilution": 7.5,
    "earnings_consistency": 7.5,
}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _ramp(value: float | None, low: float, high: float, default: float = 0.5) -> float:
    """Linear 0-1 ramp between ``low`` and ``high``. ``None`` -> ``default``."""
    if value is None:
        return default
    if high == low:
        return default
    return _clamp01((value - low) / (high - low))


def _inverse_ramp(value: float | None, low: float, high: float, default: float = 0.5) -> float:
    """1-0 ramp: lower is better (leverage, dilution)."""
    if value is None:
        return default
    return 1.0 - _ramp(value, low, high, 1.0 - default)


def quality_components(snap: FundamentalSnapshot) -> dict[str, float]:
    """Each component on 0-1, before weighting."""
    return {
        # -5% to +25% YoY revenue growth spans the scale.
        "revenue_growth": _ramp(snap.revenue_yoy, -0.05, 0.25),
        # -2pp to +3pp of operating-margin change.
        "margin_trend": _ramp(snap.operating_margin_change, -0.02, 0.03),
        # FCF positivity is close to binary; yield refines it.
        "free_cash_flow": (
            0.35 + 0.65 * _ramp(snap.fcf_yield, 0.0, 0.08)
            if snap.free_cash_flow_positive
            else 0.15 * _ramp(snap.fcf_yield, -0.05, 0.0)
        )
        if snap.free_cash_flow_positive is not None
        else 0.5,
        # Net debt / EBITDA: 0x is excellent, 4x+ is poor.
        "leverage": _inverse_ramp(snap.net_debt_to_ebitda, 0.0, 4.0),
        # ROE 0% -> 30%.
        "returns": _ramp(snap.roe, 0.0, 0.30),
        # Buybacks (negative change) score well; heavy issuance does not.
        "dilution": _inverse_ramp(snap.share_count_change, -0.02, 0.05),
        "earnings_consistency": _ramp(snap.earnings_consistency, 0.0, 1.0),
    }


def quality_score(snap: FundamentalSnapshot) -> float:
    """Weighted 0-100 fundamental quality."""
    components = quality_components(snap)
    total = sum(QUALITY_WEIGHTS[name] * value for name, value in components.items())
    return round(total, 2)


def build_fundamental_snapshot(
    ticker: str,
    facts: dict[str, Any] | None,
    as_of: datetime | None = None,
    filing_date: datetime | None = None,
) -> FundamentalSnapshot:
    """Turn raw company facts into a scored snapshot.

    ``facts`` uses the normalized key names produced by ``data.sec`` (and by the
    demo generator). Missing keys are tolerated: their components fall back to a
    neutral 0.5 rather than silently scoring zero.
    """
    facts = facts or {}
    snap = FundamentalSnapshot(
        ticker=ticker,
        as_of=as_of or datetime.now(UTC),
        source_filing_date=filing_date,
        source_form=facts.get("source_form"),
        revenue_yoy=facts.get("revenue_yoy"),
        operating_margin=facts.get("operating_margin"),
        operating_margin_change=facts.get("operating_margin_change"),
        free_cash_flow=facts.get("free_cash_flow"),
        free_cash_flow_positive=facts.get("free_cash_flow_positive"),
        fcf_yield=facts.get("fcf_yield"),
        net_debt_to_ebitda=facts.get("net_debt_to_ebitda"),
        debt_trend=facts.get("debt_trend"),
        roe=facts.get("roe"),
        roa=facts.get("roa"),
        share_count_change=facts.get("share_count_change"),
        earnings_consistency=facts.get("earnings_consistency"),
        pe_ratio=facts.get("pe_ratio"),
    )
    snap.quality_score = quality_score(snap)
    return snap


def assign_value_percentiles(snaps: dict[str, FundamentalSnapshot]) -> None:
    """Rank the universe cross-sectionally on value (spec 13).

    Mutates each snapshot's ``value_percentile`` in place. Value blends FCF yield
    (higher better), P/E (lower better) and leverage (lower better).
    """
    if not snaps:
        return

    def composite(s: FundamentalSnapshot) -> float:
        fcf = _ramp(s.fcf_yield, 0.0, 0.10)
        pe = _inverse_ramp(s.pe_ratio, 8.0, 50.0)
        lev = _inverse_ramp(s.net_debt_to_ebitda, 0.0, 4.0)
        return 0.45 * fcf + 0.35 * pe + 0.20 * lev

    scored = sorted(((composite(s), t) for t, s in snaps.items()), key=lambda x: x[0])
    n = len(scored)
    for rank, (_, ticker) in enumerate(scored):
        # rank 0 = cheapest-looking is lowest composite; percentile 100 = best value
        snaps[ticker].value_percentile = round(100.0 * (rank + 1) / n, 2)
