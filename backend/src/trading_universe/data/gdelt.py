"""GDELT adapter (spec section 27.1).

GDELT is used as broad news-DISCOVERY infrastructure, not as a sentiment source:

    GDELT discovers URL -> map to entity -> deduplicate -> extract metadata
    -> run local FinBERT -> update ticker sentiment state

Sentiment is scored locally by the configured engine, never taken from GDELT's
own tone field, so the sentiment pipeline stays under our control.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from datetime import UTC, datetime, timedelta

import httpx

from trading_universe.domain.news import NewsArticle

logger = logging.getLogger(__name__)

DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"

# Outlets whose coverage is more likely to be materially about the company.
_HIGH_SALIENCE = {
    "reuters.com", "bloomberg.com", "wsj.com", "ft.com", "cnbc.com",
    "barrons.com", "marketwatch.com", "businesswire.com", "prnewswire.com",
    "globenewswire.com", "seekingalpha.com", "investors.com",
}


class GDELTClient:
    name = "gdelt"

    def __init__(self, min_interval_seconds: float = 1.0, timeout: float = 20.0) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "TradingUniverse/0.1 (news discovery)"},
        )
        self._min_interval = min_interval_seconds
        self._last_request = 0.0
        self._lock = threading.Lock()
        self._seen: set[str] = set()

    def close(self) -> None:
        self._client.close()

    def _throttle(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_request
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_request = time.monotonic()

    def fetch_for_company(
        self, ticker: str, company_name: str, hours: int = 48, limit: int = 40
    ) -> list[NewsArticle]:
        """Query GDELT for one company.

        The query is name-based because GDELT indexes prose, not tickers; the
        ticker is then attached by us.
        """
        clean_name = _strip_suffixes(company_name)
        query = f'"{clean_name}" sourcelang:english'
        params = {
            "query": query,
            "mode": "ArtList",
            "maxrecords": str(min(limit, 250)),
            "timespan": f"{hours}h",
            "format": "json",
            "sort": "datedesc",
        }
        self._throttle()
        try:
            response = self._client.get(DOC_API, params=params)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("GDELT query failed for %s: %s", ticker, exc)
            return []

        now = datetime.now(UTC)
        out: list[NewsArticle] = []
        for item in payload.get("articles", []) or []:
            url = item.get("url")
            title = (item.get("title") or "").strip()
            if not url or not title:
                continue

            # Deduplicate on normalized title: syndication means the same story
            # arrives from a dozen outlets.
            key = hashlib.sha1(
                _normalize_title(title).encode(), usedforsecurity=False
            ).hexdigest()
            if key in self._seen:
                continue
            self._seen.add(key)

            published = _parse_gdelt_date(item.get("seendate")) or now
            if published < now - timedelta(hours=hours * 2):
                continue
            domain = (item.get("domain") or "").lower()

            out.append(
                NewsArticle(
                    article_id=f"gdelt-{key[:16]}",
                    tickers=[ticker.upper()],
                    title=title,
                    url=url,
                    source=domain or "gdelt",
                    published_at=published,
                    discovered_at=now,
                    # sentiment stays None: the local engine scores it later.
                    salience=_salience(domain, title, clean_name),
                )
            )
        return out

    def fetch(
        self, companies: dict[str, str], hours: int = 48, limit_per_company: int = 25
    ) -> list[NewsArticle]:
        """``companies`` maps ticker -> company name."""
        out: list[NewsArticle] = []
        for ticker, name in companies.items():
            out.extend(self.fetch_for_company(ticker, name, hours, limit_per_company))
        return out

    def reset_dedup(self) -> None:
        self._seen.clear()


_SUFFIX_RE = re.compile(
    r"\b(inc|corp|corporation|co|company|plc|ltd|limited|holdings|group|"
    r"technologies|international|n\.?v\.?|s\.?a\.?|the)\b\.?",
    re.IGNORECASE,
)


def _strip_suffixes(name: str) -> str:
    cleaned = _SUFFIX_RE.sub("", name)
    cleaned = re.sub(r"[^\w\s&'-]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip() or name


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()


def _parse_gdelt_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _salience(domain: str, title: str, company: str) -> float:
    """How likely this article is materially about the company, 0-1."""
    score = 0.45
    if any(domain.endswith(d) for d in _HIGH_SALIENCE):
        score += 0.30
    # A company named in the headline beats one mentioned in passing.
    if company and company.lower() in title.lower():
        score += 0.20
    return round(min(1.0, score), 3)
