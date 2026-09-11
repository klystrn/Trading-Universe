"""Rejected-signal analysis (spec section 21).

The questions this exists to answer:

    Did rejected 65-score setups outperform accepted 70-score setups?
    Which strategy threshold is too strict?
    Which sector conditions improve win rate?

Forward returns are backfilled onto signal rows by the analytics job, so accepted
and rejected signals are compared on exactly the same measurement.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Any


def rejection_breakdown(signals: list[dict[str, Any]]) -> dict[str, Any]:
    reasons: Counter[str] = Counter()
    by_strategy: dict[str, Counter[str]] = defaultdict(Counter)

    for signal in signals:
        for reason in signal.get("rejection_reasons") or []:
            reasons[reason] += 1
            by_strategy[signal["strategy_id"]][reason] += 1

    total = len(signals)
    rejected = sum(1 for s in signals if not s.get("allowed"))
    return {
        "signals": total,
        "rejected": rejected,
        "accepted": total - rejected,
        "rejection_rate": round(rejected / total, 4) if total else None,
        "reasons": reasons.most_common(),
        "by_strategy": {k: v.most_common() for k, v in by_strategy.items()},
    }


def threshold_analysis(
    signals: list[dict[str, Any]], bucket_size: int = 5, return_field: str = "forward_return_20d"
) -> list[dict[str, Any]]:
    """Forward return by score bucket, split by accepted/rejected.

    This is the evidence for moving a threshold. If the 65-69 bucket outperforms
    the 70-74 bucket on the same horizon, the threshold is in the wrong place -
    and if neither bucket has forward returns yet, the table says so rather than
    implying an answer.
    """
    buckets: dict[int, dict[str, list[float]]] = defaultdict(
        lambda: {"accepted": [], "rejected": []}
    )
    counts: dict[int, dict[str, int]] = defaultdict(lambda: {"accepted": 0, "rejected": 0})

    for signal in signals:
        score = signal.get("score_total")
        if score is None:
            continue
        bucket = int(score // bucket_size) * bucket_size
        group = "accepted" if signal.get("allowed") else "rejected"
        counts[bucket][group] += 1
        value = signal.get(return_field)
        if value is not None:
            buckets[bucket][group].append(float(value))

    out = []
    for bucket in sorted(counts):
        accepted = buckets[bucket]["accepted"]
        rejected = buckets[bucket]["rejected"]
        out.append(
            {
                "score_bucket": f"{bucket}-{bucket + bucket_size - 1}",
                "accepted_count": counts[bucket]["accepted"],
                "rejected_count": counts[bucket]["rejected"],
                "accepted_avg_return": (
                    round(statistics.fmean(accepted), 5) if accepted else None
                ),
                "rejected_avg_return": (
                    round(statistics.fmean(rejected), 5) if rejected else None
                ),
                "measured": len(accepted) + len(rejected),
            }
        )
    return out


def near_miss_summary(signals: list[dict[str, Any]], threshold: float, window: float = 5.0):
    """Signals that scored within ``window`` points of the threshold but missed."""
    return [
        {
            "ticker": s["ticker"],
            "strategy": s["strategy_id"],
            "score": s["score_total"],
            "shortfall": round(threshold - s["score_total"], 2),
            "reasons": s.get("rejection_reasons") or [],
            "generated_at": s["generated_at"],
        }
        for s in signals
        if not s.get("allowed")
        and s.get("score_total") is not None
        and threshold - window <= s["score_total"] < threshold
    ]
