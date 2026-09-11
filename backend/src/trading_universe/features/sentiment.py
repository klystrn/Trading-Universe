"""Sentiment engines and aggregation (spec 23, 27).

Two interchangeable engines behind one interface:

* ``LexiconSentimentEngine`` - a financial-domain lexicon with negation and
  intensifier handling. Zero dependencies, always available, fast enough to
  score the whole universe synchronously.
* ``FinBERTSentimentEngine`` - ProsusAI/finbert via transformers. Requires the
  optional ``[nlp]`` extra; falls back to the lexicon with a logged warning
  rather than taking the platform down.
"""

from __future__ import annotations

import logging
import math
import re
import threading
from datetime import UTC, datetime, timedelta
from typing import Protocol

from trading_universe.domain.enums import CatalystType
from trading_universe.domain.news import NewsArticle, SECEvent
from trading_universe.domain.snapshots import SentimentSnapshot

logger = logging.getLogger(__name__)

# --- financial lexicon ------------------------------------------------------
# Weights are deliberately modest; aggregate sentiment matters more than any
# single headline, and an over-confident lexicon produces false catalysts.
POSITIVE: dict[str, float] = {
    "beat": 0.7, "beats": 0.7, "exceeded": 0.6, "outperform": 0.6, "upgrade": 0.8,
    "upgraded": 0.8, "raises": 0.7, "raised": 0.6, "raise": 0.5, "growth": 0.4,
    "record": 0.6, "strong": 0.5, "stronger": 0.5, "surge": 0.7, "surged": 0.7,
    "rally": 0.5, "rallied": 0.5, "gain": 0.4, "gains": 0.4, "profit": 0.4,
    "profitable": 0.5, "expansion": 0.4, "expands": 0.4, "approval": 0.7,
    "approved": 0.7, "wins": 0.6, "won": 0.5, "awarded": 0.6, "contract": 0.4,
    "partnership": 0.4, "acquisition": 0.3, "acquires": 0.3, "dividend": 0.3,
    "buyback": 0.5, "repurchase": 0.5, "optimistic": 0.5, "confident": 0.4,
    "accelerating": 0.5, "momentum": 0.4, "breakthrough": 0.7, "launch": 0.3,
    "unveils": 0.3, "upbeat": 0.6, "robust": 0.5, "resilient": 0.4, "improved": 0.5,
    "improving": 0.5, "boosts": 0.5, "tops": 0.6, "soars": 0.8, "jumped": 0.5,
}
NEGATIVE: dict[str, float] = {
    "miss": 0.7, "misses": 0.7, "missed": 0.7, "downgrade": 0.8, "downgraded": 0.8,
    "cuts": 0.6, "cut": 0.5, "lowered": 0.6, "lowers": 0.6, "decline": 0.5,
    "declining": 0.5, "declined": 0.5, "loss": 0.6, "losses": 0.6, "weak": 0.6,
    "weaker": 0.6, "weakness": 0.6, "plunge": 0.8, "plunged": 0.8, "slump": 0.7,
    "tumble": 0.7, "tumbled": 0.7, "fell": 0.4, "falls": 0.4, "drop": 0.4,
    "warning": 0.7, "warns": 0.7, "lawsuit": 0.6, "probe": 0.6, "investigation": 0.7,
    "subpoena": 0.7, "recall": 0.7, "layoffs": 0.6, "bankruptcy": 1.0,
    "default": 0.9, "fraud": 1.0, "delay": 0.5, "delayed": 0.5, "halt": 0.6,
    "halted": 0.6, "concerns": 0.5, "concern": 0.4, "risk": 0.3, "pressure": 0.4,
    "headwind": 0.5, "headwinds": 0.5, "slowdown": 0.6, "slowing": 0.5,
    "disappointing": 0.7, "disappointed": 0.6, "shortfall": 0.7, "writedown": 0.7,
    "impairment": 0.6, "restructuring": 0.4, "softening": 0.5, "softer": 0.5,
    "regulator": 0.3, "review": 0.2, "flags": 0.3,
}
NEGATORS = {"not", "no", "never", "without", "fails", "failed", "unable", "lacks"}
INTENSIFIERS = {
    "very": 1.4, "significantly": 1.4, "sharply": 1.5, "materially": 1.3,
    "substantially": 1.4, "slightly": 0.6, "modestly": 0.7, "marginally": 0.6,
}

_TOKEN_RE = re.compile(r"[a-z']+")


class SentimentEngine(Protocol):
    name: str

    def score(self, text: str) -> float:
        """Return sentiment in [-1, 1]."""
        ...

    def score_batch(self, texts: list[str]) -> list[float]: ...


class LexiconSentimentEngine:
    """Financial-lexicon scorer with negation and intensifier handling."""

    name = "lexicon"

    def score(self, text: str) -> float:
        if not text:
            return 0.0
        tokens = _TOKEN_RE.findall(text.lower())
        if not tokens:
            return 0.0

        total = 0.0
        hits = 0
        for i, token in enumerate(tokens):
            weight = POSITIVE.get(token, 0.0) or -NEGATIVE.get(token, 0.0)
            if weight == 0.0:
                continue
            # Look back two tokens for a negator or intensifier.
            multiplier = 1.0
            for back in (1, 2):
                if i - back < 0:
                    break
                prev = tokens[i - back]
                if prev in NEGATORS:
                    multiplier *= -0.8
                elif prev in INTENSIFIERS:
                    multiplier *= INTENSIFIERS[prev]
            total += weight * multiplier
            hits += 1

        if hits == 0:
            return 0.0
        # Saturating average: many mild hits should not exceed one strong one.
        avg = total / math.sqrt(hits)
        return round(max(-1.0, min(1.0, avg / 1.6)), 4)

    def score_batch(self, texts: list[str]) -> list[float]:
        return [self.score(t) for t in texts]


class FinBERTSentimentEngine:
    """ProsusAI/finbert. Lazily loaded; degrades to the lexicon on failure."""

    name = "finbert"
    MODEL_ID = "ProsusAI/finbert"

    def __init__(self) -> None:
        self._pipeline = None
        self._fallback = LexiconSentimentEngine()
        self._lock = threading.Lock()
        self._failed = False

    def _ensure_loaded(self) -> bool:
        if self._pipeline is not None:
            return True
        if self._failed:
            return False
        with self._lock:
            if self._pipeline is not None:
                return True
            if self._failed:
                return False
            try:
                from transformers import pipeline  # type: ignore[import-not-found]

                self._pipeline = pipeline(
                    "sentiment-analysis", model=self.MODEL_ID, truncation=True, max_length=256
                )
                return True
            except Exception as exc:  # noqa: BLE001 - any failure means fall back
                logger.warning(
                    "FinBERT unavailable (%s); falling back to the lexicon engine. "
                    "Install with: pip install -e '.[nlp]'",
                    exc,
                )
                self._failed = True
                return False

    @staticmethod
    def _to_signed(label: str, score: float) -> float:
        label = label.lower()
        if label.startswith("pos"):
            return round(score, 4)
        if label.startswith("neg"):
            return round(-score, 4)
        return 0.0

    def score(self, text: str) -> float:
        if not text:
            return 0.0
        if not self._ensure_loaded():
            return self._fallback.score(text)
        try:
            result = self._pipeline(text)[0]  # type: ignore[index]
            return self._to_signed(result["label"], float(result["score"]))
        except Exception as exc:  # noqa: BLE001
            logger.warning("FinBERT scoring failed (%s); using lexicon for this batch", exc)
            return self._fallback.score(text)

    def score_batch(self, texts: list[str]) -> list[float]:
        if not texts:
            return []
        if not self._ensure_loaded():
            return self._fallback.score_batch(texts)
        try:
            results = self._pipeline(texts)  # type: ignore[misc]
            return [self._to_signed(r["label"], float(r["score"])) for r in results]
        except Exception as exc:  # noqa: BLE001
            logger.warning("FinBERT batch failed (%s); using lexicon", exc)
            return self._fallback.score_batch(texts)

    @property
    def loaded(self) -> bool:
        return self._pipeline is not None


_engine: SentimentEngine | None = None
_engine_lock = threading.Lock()


def get_sentiment_engine(name: str | None = None) -> SentimentEngine:
    global _engine
    if name is None:
        from trading_universe.settings import get_settings

        name = get_settings().sentiment_engine
    if _engine is not None and _engine.name == name:
        return _engine
    with _engine_lock:
        _engine = FinBERTSentimentEngine() if name == "finbert" else LexiconSentimentEngine()
    return _engine


# --- aggregation ------------------------------------------------------------
def _decayed_mean(
    scored: list[tuple[datetime, float, float]], now: datetime, half_life_hours: float
) -> float:
    """Salience-weighted, exponentially time-decayed mean sentiment."""
    if not scored:
        return 0.0
    num = 0.0
    den = 0.0
    for published, score, salience in scored:
        age_h = max(0.0, (now - published).total_seconds() / 3600.0)
        weight = salience * (0.5 ** (age_h / half_life_hours))
        num += weight * score
        den += weight
    if den <= 0:
        return 0.0
    return round(max(-1.0, min(1.0, num / den)), 4)


def build_sentiment_snapshot(
    ticker: str,
    articles: list[NewsArticle],
    filings: list[SECEvent] | None = None,
    now: datetime | None = None,
    engine: SentimentEngine | None = None,
) -> SentimentSnapshot:
    """Aggregate article-level sentiment into windowed ticker state."""
    now = now or datetime.now(UTC)
    engine = engine or get_sentiment_engine()

    # Score anything the provider did not pre-score.
    unscored = [a for a in articles if a.sentiment is None]
    if unscored:
        scores = engine.score_batch([f"{a.title}. {a.summary or ''}".strip() for a in unscored])
        for article, score in zip(unscored, scores, strict=True):
            article.sentiment = score
            article.sentiment_engine = engine.name
            article.processed_at = article.processed_at or now

    def window(hours: float) -> list[tuple[datetime, float, float]]:
        cutoff = now - timedelta(hours=hours)
        return [
            (a.published_at, a.sentiment or 0.0, a.salience)
            for a in articles
            if a.published_at >= cutoff
        ]

    w24, w7d, w30d = window(24), window(24 * 7), window(24 * 30)
    score_24h = _decayed_mean(w24, now, half_life_hours=8.0)
    score_7d = _decayed_mean(w7d, now, half_life_hours=48.0)
    score_30d = _decayed_mean(w30d, now, half_life_hours=168.0)

    # Trend compares the most recent day against the preceding six.
    older = [
        (a.published_at, a.sentiment or 0.0, a.salience)
        for a in articles
        if now - timedelta(days=7) <= a.published_at < now - timedelta(hours=24)
    ]
    older_score = _decayed_mean(older, now, half_life_hours=48.0)
    delta = score_24h - older_score
    if not w24:
        trend = "flat"
    elif delta > 0.08:
        trend = "improving"
    elif delta < -0.08:
        trend = "deteriorating"
    else:
        trend = "flat"

    snap = SentimentSnapshot(
        ticker=ticker,
        as_of=now,
        score_24h=score_24h,
        score_7d=score_7d,
        score_30d=score_30d,
        headline_count_24h=len(w24),
        headline_count_7d=len(w7d),
        trend=trend,
        engine=engine.name,
    )

    catalyst = _strongest_catalyst(articles, filings or [], now)
    if catalyst is not None:
        ctype, strength, at = catalyst
        snap.catalyst_type = ctype
        snap.catalyst_strength = strength
        snap.catalyst_at = at
        snap.catalyst_sessions_ago = _sessions_between(at, now)
    return snap


def _strongest_catalyst(
    articles: list[NewsArticle], filings: list[SECEvent], now: datetime
) -> tuple[CatalystType, float, datetime] | None:
    """Pick the single most material catalyst in the recent window.

    SEC 8-K items are ranked above press coverage because they are the primary
    source; a headline about a filing is an echo of it.
    """
    candidates: list[tuple[CatalystType, float, datetime]] = []
    cutoff = now - timedelta(days=10)

    for event in filings:
        if event.filed_at < cutoff or event.catalyst_type is None:
            continue
        candidates.append((event.catalyst_type, event.catalyst_strength, event.filed_at))

    for article in articles:
        if article.published_at < cutoff or article.catalyst_type is None:
            continue
        strength = 0.45 * article.salience + 0.55 * abs(article.sentiment or 0.0)
        candidates.append((article.catalyst_type, round(strength, 4), article.published_at))

    if not candidates:
        return None
    return max(candidates, key=lambda c: (c[1], c[2]))


def _sessions_between(then: datetime, now: datetime) -> int:
    """Approximate weekday sessions between two instants."""
    days = max(0, (now.date() - then.date()).days)
    full_weeks, remainder = divmod(days, 7)
    sessions = full_weeks * 5
    cursor = then.date()
    for _ in range(remainder):
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            sessions += 1
    return sessions
