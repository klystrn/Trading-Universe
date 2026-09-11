"""US House and Senate financial-disclosure adapters (spec sections 14-16, 31).

Both chambers publish periodic transaction reports on a lag: the transaction
happens, then is disclosed weeks later. Trading Universe records three distinct
instants and never conflates them:

    transaction_date  - when the trade happened (display and lag analysis only)
    disclosure_date   - when it became public (the only date a strategy may gate on)
    detected_at       - when we saw it

Backtests operate on the disclosure date, so no strategy can act on information
that was not yet public.

Both sources are HTML/PDF-backed rather than JSON APIs, and their layouts change.
The clients below degrade to an empty list and mark the source unavailable rather
than guessing, and they accept a pre-fetched local dataset so the pipeline can be
driven from a cached export.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from trading_universe.domain.enums import Chamber, PoliticalOwner, TransactionType
from trading_universe.domain.political import PoliticalTransaction

logger = logging.getLogger(__name__)

HOUSE_DISCLOSURE_URL = "https://disclosures-clerk.house.gov/FinancialDisclosure"
SENATE_EFD_URL = "https://efdsearch.senate.gov/search/"

# Disclosed amounts are ranges, not figures. These are the standard bands.
AMOUNT_BANDS: dict[str, tuple[float, float]] = {
    "$1,001 - $15,000": (1001, 15000),
    "$15,001 - $50,000": (15001, 50000),
    "$50,001 - $100,000": (50001, 100000),
    "$100,001 - $250,000": (100001, 250000),
    "$250,001 - $500,000": (250001, 500000),
    "$500,001 - $1,000,000": (500001, 1000000),
    "$1,000,001 - $5,000,000": (1000001, 5000000),
    "$5,000,001 - $25,000,000": (5000001, 25000000),
    "$1,000 - $15,000": (1000, 15000),
}

_TICKER_RE = re.compile(r"\(([A-Z][A-Z.\-]{0,6})\)")


def parse_amount_band(text: str | None) -> tuple[float, float]:
    if not text:
        return 0.0, 0.0
    cleaned = " ".join(str(text).split())
    if cleaned in AMOUNT_BANDS:
        return AMOUNT_BANDS[cleaned]
    numbers = [
        float(n.replace(",", "")) for n in re.findall(r"[\d,]+(?:\.\d+)?", cleaned)
    ]
    if len(numbers) >= 2:
        return numbers[0], numbers[1]
    if numbers:
        return numbers[0], numbers[0]
    return 0.0, 0.0


def parse_transaction_type(text: str | None) -> TransactionType | None:
    if not text:
        return None
    lowered = str(text).strip().lower()
    if lowered.startswith(("p", "purchase", "buy")):
        return TransactionType.PURCHASE
    if "partial" in lowered:
        return TransactionType.SALE_PARTIAL
    if "full" in lowered:
        return TransactionType.SALE_FULL
    if lowered.startswith(("s", "sale", "sell")):
        return TransactionType.SALE
    if lowered.startswith("e"):
        return TransactionType.EXCHANGE
    return None


def parse_owner(text: str | None) -> PoliticalOwner:
    if not text:
        return PoliticalOwner.UNKNOWN
    lowered = str(text).strip().lower()
    return {
        "sp": PoliticalOwner.SPOUSE, "spouse": PoliticalOwner.SPOUSE,
        "dc": PoliticalOwner.DEPENDENT, "dependent": PoliticalOwner.DEPENDENT,
        "jt": PoliticalOwner.JOINT, "joint": PoliticalOwner.JOINT,
        "self": PoliticalOwner.SELF, "sf": PoliticalOwner.SELF,
    }.get(lowered, PoliticalOwner.SELF if lowered else PoliticalOwner.UNKNOWN)


def extract_ticker(asset_description: str | None, explicit: str | None = None) -> str | None:
    if explicit and explicit.strip() and explicit.strip() != "--":
        return explicit.strip().upper()
    if not asset_description:
        return None
    match = _TICKER_RE.search(asset_description)
    return match.group(1).upper() if match else None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d %B %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


class DisclosureClient:
    """Shared parsing for both chambers.

    ``load_csv`` is the supported ingestion path: point it at an export of the
    chamber's periodic transaction reports. ``fetch_disclosures`` attempts a live
    fetch and returns an empty list when the layout has moved, so a scraper
    breaking degrades the political strategies rather than corrupting them.
    """

    name = "disclosures"
    chamber: Chamber = Chamber.HOUSE
    source_url: str = HOUSE_DISCLOSURE_URL

    def __init__(self, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "TradingUniverse/0.1 (research; contact in .env)"},
            follow_redirects=True,
        )
        self.last_error: str | None = None

    def close(self) -> None:
        self._client.close()

    # -- ingestion ----------------------------------------------------------
    def load_csv(self, path: str | Path, since: date | None = None) -> list[PoliticalTransaction]:
        path = Path(path)
        if not path.exists():
            self.last_error = f"{path} not found"
            return []
        with path.open(newline="", encoding="utf-8") as fh:
            return self.parse_rows(list(csv.DictReader(fh)), since)

    def parse_rows(
        self, rows: list[dict[str, str]], since: date | None = None
    ) -> list[PoliticalTransaction]:
        """Parse disclosure rows. Unrecognised or incomplete rows are skipped,
        never guessed at."""
        now = datetime.now(UTC)
        out: list[PoliticalTransaction] = []

        for index, row in enumerate(rows):
            lookup = {k.strip().lower().replace(" ", "_"): v for k, v in row.items() if k}

            def get(*names: str, _row: dict[str, str] = lookup) -> str | None:
                for name in names:
                    value = _row.get(name)
                    if value not in (None, "", "--"):
                        return str(value)
                return None

            ticker = extract_ticker(
                get("asset_description", "asset", "asset_name"), get("ticker", "symbol")
            )
            if not ticker:
                continue

            ttype = parse_transaction_type(get("type", "transaction_type", "txn_type"))
            if ttype is None:
                continue

            txn_date = _parse_date(get("transaction_date", "txn_date", "date"))
            disc_date = _parse_date(get("disclosure_date", "filing_date", "report_date"))
            # Without a disclosure date we cannot honestly place the event in
            # time, and a guess would poison every backtest that uses it.
            if disc_date is None:
                continue
            if txn_date is None:
                txn_date = disc_date
            if since and disc_date < since:
                continue

            low, high = parse_amount_band(get("amount", "amount_range", "value"))
            politician = get("representative", "senator", "member", "name") or "Unknown"

            out.append(
                PoliticalTransaction(
                    transaction_id=get("transaction_id", "id")
                    or f"{self.chamber.value.lower()}-{disc_date}-{ticker}-{index}",
                    politician=politician.strip(),
                    chamber=self.chamber,
                    party=get("party"),
                    state=get("state", "district"),
                    owner=parse_owner(get("owner")),
                    ticker=ticker,
                    asset_description=get("asset_description", "asset"),
                    transaction_type=ttype,
                    amount_low=low,
                    amount_high=high,
                    transaction_date=txn_date,
                    disclosure_date=disc_date,
                    detected_at=now,
                    source_url=get("ptr_link", "link", "url") or self.source_url,
                )
            )
        return out

    def fetch_disclosures(self, since: date | None = None) -> list[PoliticalTransaction]:
        """Best-effort live fetch.

        Both chambers gate their search behind session state and serve results as
        HTML tables or PDFs. Rather than ship a brittle scraper that silently
        returns partial data, this reports the source unavailable and defers to
        ``load_csv``.
        """
        self.last_error = (
            f"{self.chamber.value} disclosures require a periodic-transaction-report "
            f"export; load one with load_csv(). Source: {self.source_url}"
        )
        logger.info(self.last_error)
        return []

    def fetch_csv_url(
        self, url: str, since: date | None = None
    ) -> list[PoliticalTransaction]:
        """Parse a hosted CSV export of periodic transaction reports."""
        try:
            response = self._client.get(url)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            logger.warning("%s disclosure fetch failed: %s", self.chamber.value, exc)
            return []
        self.last_error = None
        return self.parse_rows(list(csv.DictReader(io.StringIO(response.text))), since)


class HouseDisclosureClient(DisclosureClient):
    name = "house"
    chamber = Chamber.HOUSE
    source_url = HOUSE_DISCLOSURE_URL


class SenateDisclosureClient(DisclosureClient):
    name = "senate"
    chamber = Chamber.SENATE
    source_url = SENATE_EFD_URL
