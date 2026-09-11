"""SEC EDGAR adapter (spec sections 23, 26).

Event-driven where possible: detect a new filing, parse the metrics that matter,
recalculate the fundamental score, invalidate the old one. Fundamentals do not
need second-by-second polling.

SEC's fair-access policy requires a descriptive User-Agent with contact details
and caps request rates. Both are honoured here; set SEC_USER_AGENT in .env.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from trading_universe.domain.enums import CatalystType
from trading_universe.domain.news import SECEvent
from trading_universe.settings import get_settings

logger = logging.getLogger(__name__)

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

# 8-K item codes that carry genuine trading information (spec section 10).
ITEM_CATALYSTS: dict[str, tuple[CatalystType, float]] = {
    "1.01": (CatalystType.CONTRACT, 0.70),      # material definitive agreement
    "1.02": (CatalystType.CONTRACT, 0.55),      # termination of agreement
    "2.01": (CatalystType.ACQUISITION, 0.80),   # completion of acquisition
    "2.02": (CatalystType.EARNINGS, 0.85),      # results of operations
    "2.03": (CatalystType.MATERIAL_8K, 0.50),   # direct financial obligation
    "2.05": (CatalystType.MATERIAL_8K, 0.55),   # costs of exit/disposal
    "2.06": (CatalystType.MATERIAL_8K, 0.65),   # material impairment
    "3.01": (CatalystType.REGULATORY, 0.70),    # delisting notice
    "5.02": (CatalystType.MANAGEMENT, 0.55),    # director/officer departure
    "7.01": (CatalystType.MANAGEMENT, 0.40),    # regulation FD disclosure
    "8.01": (CatalystType.OTHER, 0.45),         # other events
}

# XBRL concepts -> our normalized names. Several US-GAAP tags mean the same
# thing depending on filer; the first present wins.
CONCEPTS: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    "equity": ["StockholdersEquity"],
    "assets": ["Assets"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "shares": ["CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding"],
}


class SECClient:
    """Rate-limited EDGAR client."""

    name = "sec"

    def __init__(self, min_interval_seconds: float = 0.12, timeout: float = 20.0) -> None:
        settings = get_settings()
        self._headers = {
            "User-Agent": settings.sec_user_agent,
            "Accept-Encoding": "gzip, deflate",
        }
        self._min_interval = min_interval_seconds
        self._last_request = 0.0
        self._lock = threading.Lock()
        self._client = httpx.Client(timeout=timeout, headers=self._headers)
        self._cik_map: dict[str, int] | None = None
        self._facts_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}

    def close(self) -> None:
        self._client.close()

    def _get(self, url: str) -> Any:
        with self._lock:
            elapsed = time.monotonic() - self._last_request
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_request = time.monotonic()
        response = self._client.get(url)
        response.raise_for_status()
        return response.json()

    # -- CIK lookup ---------------------------------------------------------
    def cik_for(self, ticker: str) -> int | None:
        if self._cik_map is None:
            try:
                raw = self._get(COMPANY_TICKERS_URL)
                self._cik_map = {
                    str(row["ticker"]).upper(): int(row["cik_str"]) for row in raw.values()
                }
            except Exception as exc:  # noqa: BLE001
                logger.warning("SEC ticker map unavailable: %s", exc)
                self._cik_map = {}
        return self._cik_map.get(ticker.upper())

    # -- filings ------------------------------------------------------------
    def get_recent_filings(
        self, ticker: str, since: datetime | None = None, limit: int = 25
    ) -> list[SECEvent]:
        cik = self.cik_for(ticker)
        if cik is None:
            return []
        try:
            data = self._get(SUBMISSIONS_URL.format(cik=cik))
        except Exception as exc:  # noqa: BLE001
            logger.warning("SEC submissions failed for %s: %s", ticker, exc)
            return []

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        items_col = recent.get("items", [""] * len(forms))
        primary = recent.get("primaryDocument", [""] * len(forms))
        now = datetime.now(UTC)
        cutoff = since or (now - timedelta(days=90))

        out: list[SECEvent] = []
        for i in range(min(len(forms), limit * 4)):
            form = forms[i]
            if form not in ("8-K", "10-Q", "10-K", "6-K", "20-F"):
                continue
            filed = datetime.fromisoformat(dates[i]).replace(tzinfo=UTC)
            if filed < cutoff:
                continue
            items = [x.strip() for x in str(items_col[i] or "").split(",") if x.strip()]
            catalyst, strength = self._catalyst_for(form, items)
            accession = str(accessions[i]).replace("-", "")
            out.append(
                SECEvent(
                    accession=str(accessions[i]),
                    ticker=ticker.upper(),
                    cik=str(cik),
                    form=form,
                    items=items,
                    title=f"{form} filed {dates[i]}",
                    url=(
                        f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/"
                        f"{primary[i]}" if primary[i] else None
                    ),
                    filed_at=filed,
                    discovered_at=now,
                    processed_at=now,
                    catalyst_type=catalyst,
                    catalyst_strength=strength,
                )
            )
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _catalyst_for(
        form: str, items: list[str]
    ) -> tuple[CatalystType | None, float]:
        if form in ("10-Q", "10-K"):
            return CatalystType.EARNINGS, 0.45
        best: tuple[CatalystType | None, float] = (None, 0.0)
        for item in items:
            mapped = ITEM_CATALYSTS.get(item)
            if mapped and mapped[1] > best[1]:
                best = mapped
        if best[0] is None and form == "8-K":
            return CatalystType.MATERIAL_8K, 0.35
        return best

    # -- company facts ------------------------------------------------------
    def get_company_facts(self, ticker: str, cache_hours: float = 12.0) -> dict[str, Any] | None:
        cached = self._facts_cache.get(ticker.upper())
        if cached and datetime.now(UTC) - cached[0] < timedelta(hours=cache_hours):
            return cached[1]

        cik = self.cik_for(ticker)
        if cik is None:
            return None
        try:
            raw = self._get(COMPANY_FACTS_URL.format(cik=cik))
        except Exception as exc:  # noqa: BLE001
            logger.warning("SEC companyfacts failed for %s: %s", ticker, exc)
            return None

        parsed = parse_company_facts(raw)
        self._facts_cache[ticker.upper()] = (datetime.now(UTC), parsed)
        return parsed


def _series(raw: dict[str, Any], concepts: list[str]) -> list[dict[str, Any]]:
    """Pull the most recent annual/quarterly datapoints for the first concept
    that exists, newest first."""
    facts = raw.get("facts", {}).get("us-gaap", {})
    dei = raw.get("facts", {}).get("dei", {})
    for concept in concepts:
        node = facts.get(concept) or dei.get(concept)
        if not node:
            continue
        units = node.get("units", {})
        series = units.get("USD") or units.get("shares") or next(iter(units.values()), [])
        dated = [p for p in series if p.get("end")]
        return sorted(dated, key=lambda p: p["end"], reverse=True)
    return []


def _latest(points: list[dict[str, Any]], form: str | None = None) -> float | None:
    for point in points:
        if form and point.get("form") != form:
            continue
        value = point.get("val")
        if value is not None:
            return float(value)
    return None


def _year_ago(points: list[dict[str, Any]]) -> float | None:
    """Same fiscal period one year earlier, so growth is like-for-like."""
    if not points:
        return None
    newest = points[0]
    fp, fy = newest.get("fp"), newest.get("fy")
    if fy is None:
        return None
    for point in points[1:]:
        if point.get("fp") == fp and point.get("fy") == fy - 1:
            return float(point["val"])
    return None


def parse_company_facts(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize XBRL company facts into the keys the feature engine expects."""
    revenue = _series(raw, CONCEPTS["revenue"])
    operating = _series(raw, CONCEPTS["operating_income"])
    ocf = _series(raw, CONCEPTS["operating_cash_flow"])
    capex = _series(raw, CONCEPTS["capex"])
    equity = _series(raw, CONCEPTS["equity"])
    assets = _series(raw, CONCEPTS["assets"])
    debt = _series(raw, CONCEPTS["long_term_debt"])
    cash = _series(raw, CONCEPTS["cash"])
    shares = _series(raw, CONCEPTS["shares"])
    net_income = _series(raw, CONCEPTS["net_income"])

    revenue_now = _latest(revenue)
    revenue_prior = _year_ago(revenue)
    operating_now = _latest(operating)
    operating_prior = _year_ago(operating)

    out: dict[str, Any] = {"source_form": (revenue[0].get("form") if revenue else None)}

    if revenue_now and revenue_prior:
        out["revenue_yoy"] = round((revenue_now - revenue_prior) / abs(revenue_prior), 5)
    if revenue_now and operating_now:
        margin = operating_now / revenue_now
        out["operating_margin"] = round(margin, 5)
        if revenue_prior and operating_prior:
            out["operating_margin_change"] = round(
                margin - (operating_prior / revenue_prior), 5
            )

    ocf_now, capex_now = _latest(ocf), _latest(capex)
    if ocf_now is not None:
        fcf = ocf_now - abs(capex_now or 0.0)
        out["free_cash_flow"] = round(fcf, 2)
        out["free_cash_flow_positive"] = fcf > 0

    equity_now, net_income_now = _latest(equity), _latest(net_income)
    if equity_now and net_income_now is not None and equity_now != 0:
        out["roe"] = round(net_income_now / equity_now, 5)
    assets_now = _latest(assets)
    if assets_now and net_income_now is not None and assets_now != 0:
        out["roa"] = round(net_income_now / assets_now, 5)

    debt_now, cash_now = _latest(debt), _latest(cash)
    if debt_now is not None and operating_now:
        net_debt = debt_now - (cash_now or 0.0)
        # EBITDA is not an XBRL concept; operating income is the honest proxy
        # available from companyfacts without depreciation reconstruction.
        out["net_debt_to_ebitda"] = round(net_debt / operating_now, 3) if operating_now else None
    debt_prior = _year_ago(debt)
    if debt_now is not None and debt_prior:
        change = (debt_now - debt_prior) / abs(debt_prior)
        out["debt_trend"] = (
            "improving" if change < -0.05 else "deteriorating" if change > 0.15 else "stable"
        )

    shares_now, shares_prior = _latest(shares), _year_ago(shares)
    if shares_now and shares_prior:
        out["share_count_change"] = round((shares_now - shares_prior) / shares_prior, 5)

    # Earnings consistency: share of the last eight reported periods profitable.
    recent_income = [p for p in net_income[:8] if p.get("val") is not None]
    if recent_income:
        out["earnings_consistency"] = round(
            sum(1 for p in recent_income if float(p["val"]) > 0) / len(recent_income), 3
        )

    return out
