"""Political disclosure features (spec 14, 15, 16, 31).

Every window here is measured from the DISCLOSURE date. The transaction date is
retained for display and lag analysis only - using it to gate a signal would
give the backtest information nobody could have acted on.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

from trading_universe.domain.enums import Chamber, TransactionType
from trading_universe.domain.political import PoliticalTransaction
from trading_universe.domain.snapshots import PoliticalSnapshot


def _decay(age_days: float, half_life_days: float) -> float:
    if half_life_days <= 0:
        return 1.0
    return 0.5 ** (max(0.0, age_days) / half_life_days)


def amount_band_score(amount_high: float, curve: dict[int, float] | None = None) -> float:
    """Map a disclosed amount band onto 0-1 using the configured curve.

    Disclosures are ranges, so the band's upper bound is the comparable figure.
    """
    curve = curve or {1000: 0.15, 15000: 0.40, 50000: 0.60,
                      100000: 0.75, 250000: 0.90, 500000: 1.00}
    best = 0.0
    for threshold in sorted(int(k) for k in curve):
        if amount_high >= threshold:
            best = float(curve[threshold])
    return best


def filter_by_disclosure(
    transactions: list[PoliticalTransaction], ticker: str, since: date
) -> list[PoliticalTransaction]:
    return [
        t for t in transactions
        if t.ticker.upper() == ticker.upper() and t.disclosure_date >= since
    ]


def build_political_snapshot(
    ticker: str,
    transactions: list[PoliticalTransaction],
    now: datetime | None = None,
    consensus_window_days: int = 30,
    repeat_window_days: int = 180,
    consensus_half_life_days: float = 14.0,
    repeat_half_life_days: float = 30.0,
    chamber_overlap_bonus: float = 0.15,
    amount_curve: dict[int, float] | None = None,
) -> PoliticalSnapshot:
    now = now or datetime.now(UTC)
    today = now.date()

    short_window = filter_by_disclosure(
        transactions, ticker, today - timedelta(days=consensus_window_days)
    )
    long_window = filter_by_disclosure(
        transactions, ticker, today - timedelta(days=repeat_window_days)
    )

    snap = PoliticalSnapshot(ticker=ticker.upper(), as_of=now)
    if not long_window:
        return snap

    purchases_short = [t for t in short_window if t.is_purchase]
    sales_short = [t for t in short_window if not t.is_purchase]
    purchases_long = [t for t in long_window if t.is_purchase]
    sales_long = [t for t in long_window if not t.is_purchase]

    snap.purchases_30d = len(purchases_short)
    snap.sales_30d = len(sales_short)
    snap.distinct_politicians_30d = len({t.identity_key for t in purchases_short})
    snap.distinct_politicians_180d = len({t.identity_key for t in purchases_long})
    snap.chambers_30d = sorted({t.chamber.value for t in purchases_short})
    snap.total_amount_low_30d = round(sum(t.amount_low for t in purchases_short), 2)
    snap.total_amount_high_30d = round(sum(t.amount_high for t in purchases_short), 2)
    snap.largest_band_usd = max((t.amount_high for t in purchases_short), default=0.0)
    snap.politicians_with_sales = sorted({t.identity_key for t in sales_long})

    newest = max(long_window, key=lambda t: t.disclosure_date)
    snap.newest_disclosure_at = datetime(
        newest.disclosure_date.year, newest.disclosure_date.month,
        newest.disclosure_date.day, tzinfo=UTC,
    )
    snap.newest_disclosure_age_days = float((today - newest.disclosure_date).days)
    snap.newest_transaction_lag_days = float(newest.disclosure_lag_days)

    # Repeat buyers within the long window (purchases only).
    repeat: dict[str, int] = {}
    for t in purchases_long:
        repeat[t.identity_key] = repeat.get(t.identity_key, 0) + 1
    snap.repeat_buyers = dict(sorted(repeat.items(), key=lambda kv: -kv[1]))

    # --- freshness subscore (P1) ------------------------------------------
    snap.freshness_score = round(
        _decay(snap.newest_disclosure_age_days, consensus_half_life_days), 4
    )

    # --- consensus subscore (P2) ------------------------------------------
    # More independent disclosed buyers, more recently, in larger bands, with
    # both chambers represented, and net of any sales in the window.
    if purchases_short:
        per_politician: dict[str, float] = {}
        for t in purchases_short:
            age = float((today - t.disclosure_date).days)
            contribution = _decay(age, consensus_half_life_days) * amount_band_score(
                t.amount_high, amount_curve
            )
            # One politician buying three times is not three politicians.
            per_politician[t.identity_key] = max(
                per_politician.get(t.identity_key, 0.0), contribution
            )
        breadth = sum(per_politician.values())
        # Saturating: the 2nd and 3rd buyer matter a lot, the 8th much less.
        consensus = 1.0 - math.exp(-breadth / 1.8)
        if len(snap.chambers_30d) > 1:
            consensus = min(1.0, consensus * (1.0 + chamber_overlap_bonus))
        # Sales in the window are evidence against consensus.
        if sales_short:
            sale_weight = sum(
                _decay(float((today - t.disclosure_date).days), consensus_half_life_days)
                for t in sales_short
            )
            consensus *= max(0.0, 1.0 - 0.35 * sale_weight)
        snap.consensus_score = round(max(0.0, min(1.0, consensus)), 4)

    # --- repeat-buyer subscore (P3) ---------------------------------------
    if repeat:
        top_key, top_count = next(iter(snap.repeat_buyers.items()))
        theirs = [t for t in purchases_long if t.identity_key == top_key]
        newest_theirs = max(t.disclosure_date for t in theirs)
        recency = _decay(float((today - newest_theirs).days), repeat_half_life_days)
        frequency = min(1.0, (top_count - 1) / 3.0)
        size = amount_band_score(max(t.amount_high for t in theirs), amount_curve)
        no_sales = 0.0 if top_key in snap.politicians_with_sales else 1.0
        # historical_follow_through requires post-disclosure return history that
        # only accumulates with live operation; neutral until analytics fills it.
        follow_through = 0.5
        snap.repeat_score = round(
            0.30 * recency
            + 0.25 * frequency
            + 0.20 * size
            + 0.15 * no_sales
            + 0.10 * follow_through,
            4,
        )

    return snap


def fresh_purchase_score(
    snap: PoliticalSnapshot,
    max_age_days: int = 21,
    min_amount: float = 15000.0,
    amount_curve: dict[int, float] | None = None,
) -> float:
    """P1 subscore: one recent, meaningful, disclosed purchase (0-1)."""
    if snap.purchases_30d == 0 or snap.newest_disclosure_age_days is None:
        return 0.0
    if snap.newest_disclosure_age_days > max_age_days:
        return 0.0
    if snap.largest_band_usd < min_amount:
        return 0.0
    recency = 1.0 - (snap.newest_disclosure_age_days / max(1.0, max_age_days))
    size = amount_band_score(snap.largest_band_usd, amount_curve)
    return round(max(0.0, min(1.0, 0.55 * recency + 0.45 * size)), 4)


def summarize_by_ticker(
    transactions: list[PoliticalTransaction], now: datetime | None = None, **kwargs
) -> dict[str, PoliticalSnapshot]:
    """Build one snapshot per ticker that appears in ``transactions``."""
    now = now or datetime.now(UTC)
    tickers = {t.ticker.upper() for t in transactions}
    return {
        ticker: build_political_snapshot(ticker, transactions, now=now, **kwargs)
        for ticker in tickers
    }


def chamber_counts(transactions: list[PoliticalTransaction]) -> dict[str, int]:
    out = {Chamber.HOUSE.value: 0, Chamber.SENATE.value: 0}
    for t in transactions:
        out[t.chamber.value] = out.get(t.chamber.value, 0) + 1
    return out


def purchase_sale_counts(transactions: list[PoliticalTransaction]) -> dict[str, int]:
    return {
        TransactionType.PURCHASE.value: sum(1 for t in transactions if t.is_purchase),
        TransactionType.SALE.value: sum(1 for t in transactions if not t.is_purchase),
    }
