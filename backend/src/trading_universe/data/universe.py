"""The tradable universe: S&P 500 + Nasdaq 100 constituents and their taxonomy."""

from __future__ import annotations

import csv
import math
import threading
from pathlib import Path

from trading_universe.config import get_config
from trading_universe.domain.market import Sector, Stock, Subsector

# Dual-class listings that represent the same company. The listed ticker is the
# one rendered in the 3D scene; the others stay tradable but are deduplicated out
# of the visualization so one company is one star (spec section 60).
DEDUP_GROUPS: dict[str, str] = {
    "GOOGL": "ALPHABET",
    "GOOG": "ALPHABET",
    "FOXA": "FOX",
    "FOX": "FOX",
    "NWSA": "NEWSCORP",
    "NWS": "NEWSCORP",
}
DEDUP_PRIMARY: dict[str, str] = {
    "ALPHABET": "GOOGL",
    "FOX": "FOXA",
    "NEWSCORP": "NWSA",
}


class UniverseRegistry:
    """In-memory index of the universe, loaded once from the constituents CSV."""

    def __init__(self, csv_path: Path | None = None) -> None:
        cfg = get_config()
        self._path = csv_path or cfg.universe.constituents_path
        self._lock = threading.RLock()
        self._stocks: dict[str, Stock] = {}
        self._sectors: dict[str, Sector] = {}
        self._subsectors: dict[str, Subsector] = {}
        self.load()

    # -- loading -----------------------------------------------------------
    def load(self) -> None:
        cfg = get_config()
        with self._lock:
            self._sectors = {
                s["id"]: Sector(
                    id=s["id"], label=s["label"], short=s.get("short", s["label"]),
                    hue=int(s.get("hue", 200)),
                )
                for s in cfg.universe.sectors
            }
            self._stocks = {}
            self._subsectors = {}

            if not self._path.exists():
                raise FileNotFoundError(f"constituents file missing: {self._path}")

            with self._path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    ticker = (row.get("ticker") or "").strip().upper()
                    if not ticker:
                        continue
                    sector = (row.get("sector") or "").strip()
                    subsector = (row.get("subsector") or "Other").strip()
                    group = DEDUP_GROUPS.get(ticker)
                    stock = Stock(
                        ticker=ticker,
                        name=(row.get("name") or ticker).strip(),
                        sector=sector,
                        subsector=subsector,
                        indices=[
                            i for i in (row.get("indices") or "").split("|") if i
                        ],
                        market_cap_musd=float(row.get("market_cap_musd") or 0.0),
                        dedup_group=group,
                        primary_class=(group is None or DEDUP_PRIMARY.get(group) == ticker),
                    )
                    self._stocks[ticker] = stock

                    sub_id = f"{sector}:{subsector}"
                    if sub_id not in self._subsectors:
                        self._subsectors[sub_id] = Subsector(
                            id=sub_id, label=subsector, sector_id=sector
                        )

            unknown = {s.sector for s in self._stocks.values()} - set(self._sectors)
            if unknown:
                raise ValueError(
                    f"constituents reference sectors absent from universe.yaml: "
                    f"{sorted(unknown)}"
                )

    # -- lookups -----------------------------------------------------------
    @property
    def stocks(self) -> dict[str, Stock]:
        return self._stocks

    @property
    def sectors(self) -> dict[str, Sector]:
        return self._sectors

    @property
    def subsectors(self) -> dict[str, Subsector]:
        return self._subsectors

    def tickers(self, index: str | None = None) -> list[str]:
        if index is None:
            return sorted(self._stocks)
        return sorted(t for t, s in self._stocks.items() if index in s.indices)

    def get(self, ticker: str) -> Stock | None:
        return self._stocks.get(ticker.upper())

    def sector_of(self, ticker: str) -> str:
        s = self.get(ticker)
        return s.sector if s else "unknown"

    def sector_map(self) -> dict[str, str]:
        return {t: s.sector for t, s in self._stocks.items()}

    def by_sector(self, sector_id: str) -> list[Stock]:
        return [s for s in self._stocks.values() if s.sector == sector_id]

    def by_subsector(self, sector_id: str, subsector: str) -> list[Stock]:
        return [
            s
            for s in self._stocks.values()
            if s.sector == sector_id and s.subsector == subsector
        ]

    def subsectors_of(self, sector_id: str) -> list[str]:
        return sorted({s.subsector for s in self._stocks.values() if s.sector == sector_id})

    def renderable(self) -> list[Stock]:
        """Stocks that get their own star in the universe (deduplicated)."""
        return [s for s in self._stocks.values() if s.primary_class]

    # -- derived visual quantities ------------------------------------------
    def size_for(self, ticker: str) -> float:
        """Log-scaled market-cap size so mega-caps do not dwarf the universe."""
        viz = get_config().universe.visualization
        lo = float(viz.get("size_min", 0.35))
        hi = float(viz.get("size_max", 2.4))
        stock = self.get(ticker)
        if stock is None or stock.market_cap_musd <= 0:
            return lo
        caps = [s.market_cap_musd for s in self._stocks.values() if s.market_cap_musd > 0]
        if not caps:
            return lo
        log_cap = math.log10(stock.market_cap_musd)
        log_min = math.log10(min(caps))
        log_max = math.log10(max(caps))
        if log_max <= log_min:
            return lo
        t = (log_cap - log_min) / (log_max - log_min)
        return round(lo + t * (hi - lo), 4)


_registry: UniverseRegistry | None = None
_lock = threading.Lock()


def get_universe() -> UniverseRegistry:
    global _registry
    if _registry is None:
        with _lock:
            if _registry is None:
                _registry = UniverseRegistry()
    return _registry


def reload_universe() -> UniverseRegistry:
    global _registry
    with _lock:
        _registry = UniverseRegistry()
    return _registry
