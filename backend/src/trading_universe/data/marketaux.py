"""Marketaux adapter (spec section 27.2).

Used selectively for financial-news enrichment and targeted queries, NOT as the
primary firehose: the free tier's daily request cap makes that impossible, and
pretending otherwise would produce silent gaps. Quota consumption is tracked and
surfaced on the Data Health panel.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, date, datetime

import httpx

from trading_universe.domain.news import NewsArticle
from trading_universe.settings import get_settings

logger = logging.getLogger(__name__)

API_URL = "https://api.marketaux.com/v1/news/all"
FREE_TIER_DAILY_REQUESTS = 100


class MarketauxClient:
    name = "marketaux"

    def __init__(self, api_key: str | None = None, daily_limit: int = FREE_TIER_DAILY_REQUESTS):
        self.api_key = api_key or get_settings().marketaux_api_key
        self.daily_limit = daily_limit
        self._client = httpx.Client(timeout=20.0)
        self._lock = threading.Lock()
        self._used_today = 0
        self._quota_date = date.today()

    def close(self) -> None:
        self._client.close()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def quota_used(self) -> int:
        self._roll_day()
        return self._used_today

    @property
    def quota_remaining(self) -> int:
        return max(0, self.daily_limit - self.quota_used)

    def _roll_day(self) -> None:
        with self._lock:
            today = date.today()
            if today != self._quota_date:
                self._quota_date = today
                self._used_today = 0

    def fetch(
        self, tickers: list[str], limit: int = 10, published_after: datetime | None = None
    ) -> list[NewsArticle]:
        if not self.configured:
            return []
        self._roll_day()
        if self.quota_remaining <= 0:
            logger.warning("Marketaux daily quota exhausted (%d requests)", self.daily_limit)
            return []
        if not tickers:
            return []

        params: dict[str, str] = {
            "api_token": self.api_key,
            # The free tier caps symbols per request; batch conservatively.
            "symbols": ",".join(t.upper() for t in tickers[:10]),
            "filter_entities": "true",
            "language": "en",
            "limit": str(min(limit, 50)),
        }
        if published_after:
            params["published_after"] = published_after.strftime("%Y-%m-%dT%H:%M")

        with self._lock:
            self._used_today += 1
        try:
            response = self._client.get(API_URL, params=params)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Marketaux request failed: %s", exc)
            return []

        now = datetime.now(UTC)
        out: list[NewsArticle] = []
        for item in payload.get("data", []) or []:
            entities = item.get("entities", []) or []
            matched = [
                str(e.get("symbol", "")).upper()
                for e in entities
                if e.get("symbol") and str(e["symbol"]).upper() in {t.upper() for t in tickers}
            ]
            if not matched:
                continue
            published = _parse_iso(item.get("published_at")) or now
            # Marketaux ships its own entity sentiment; we keep it as salience
            # input only and let the local engine own the sentiment score.
            relevance = max(
                (float(e.get("match_score") or 0.0) for e in entities if e.get("symbol")),
                default=0.0,
            )
            out.append(
                NewsArticle(
                    article_id=f"marketaux-{item.get('uuid')}",
                    tickers=matched,
                    title=item.get("title") or "",
                    url=item.get("url"),
                    source=item.get("source") or "marketaux",
                    summary=item.get("description"),
                    published_at=published,
                    discovered_at=now,
                    salience=round(min(1.0, 0.5 + relevance / 200.0), 3),
                )
            )
        return out


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None
