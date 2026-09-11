"""News and SEC filing objects with full provenance timestamps (spec 28)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from trading_universe.domain.enums import CatalystType


class NewsArticle(BaseModel):
    article_id: str
    tickers: list[str] = Field(default_factory=list)
    title: str
    url: str | None = None
    source: str = "unknown"
    summary: str | None = None

    published_at: datetime
    discovered_at: datetime
    processed_at: datetime | None = None

    sentiment: float | None = Field(default=None, ge=-1.0, le=1.0)
    sentiment_engine: str | None = None
    catalyst_type: CatalystType | None = None
    salience: float = Field(default=0.5, ge=0.0, le=1.0)

    def source_latency_seconds(self) -> float:
        return max(0.0, (self.discovered_at - self.published_at).total_seconds())

    def processing_latency_seconds(self) -> float | None:
        if self.processed_at is None:
            return None
        return max(0.0, (self.processed_at - self.discovered_at).total_seconds())


class SECEvent(BaseModel):
    accession: str
    ticker: str
    cik: str | None = None
    form: str
    items: list[str] = Field(default_factory=list, description="8-K item codes, e.g. 2.02")
    title: str | None = None
    url: str | None = None

    filed_at: datetime
    discovered_at: datetime
    processed_at: datetime | None = None

    catalyst_type: CatalystType | None = None
    catalyst_strength: float = Field(default=0.0, ge=0.0, le=1.0)
