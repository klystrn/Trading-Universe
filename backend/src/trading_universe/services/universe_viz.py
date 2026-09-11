"""Build the compact visualization payload for the 3D universe (spec 45, 49, 77).

The frontend must not receive every financial metric on every animation frame.
This produces a lean per-entity state: position, size, orbit speed, intensity and
the few flags the shaders and filters actually branch on.

Encoding (spec section 49):
    orbit speed  <- trading volume, deliberately restrained
    intensity    <- price movement
    size         <- market cap, logarithmically scaled
    position     <- sector / subsector membership
"""

from __future__ import annotations

import math
from typing import Any

from trading_universe.config import get_config
from trading_universe.data.universe import UniverseRegistry
from trading_universe.domain.market import Quote
from trading_universe.domain.portfolio import Position
from trading_universe.domain.signals import Signal
from trading_universe.domain.snapshots import PoliticalSnapshot, TechnicalSnapshot

GOLDEN_ANGLE = math.pi * (3.0 - math.sqrt(5.0))


def _sector_position(index: int, total: int, radius: float, spread: float) -> list[float]:
    """Place sector galaxies on a golden-angle spiral so none crowd each other."""
    if total <= 1:
        return [0.0, 0.0, 0.0]
    angle = index * GOLDEN_ANGLE
    # sqrt keeps the outer rings from bunching up.
    r = radius * math.sqrt((index + 0.5) / total)
    y = spread * (((index % 5) / 4.0) - 0.5) * 2.0
    return [round(r * math.cos(angle), 3), round(y, 3), round(r * math.sin(angle), 3)]


def _offset(index: int, total: int, radius: float, seed: float = 0.0) -> list[float]:
    """Distribute children around their parent on a Fibonacci sphere."""
    if total <= 0:
        return [0.0, 0.0, 0.0]
    i = index + 0.5
    phi = math.acos(1.0 - 2.0 * i / total)
    theta = GOLDEN_ANGLE * i + seed
    return [
        round(radius * math.sin(phi) * math.cos(theta), 3),
        round(radius * math.cos(phi) * 0.16, 3),  # a thin disc: stars lie in the galaxy plane
        round(radius * math.sin(phi) * math.sin(theta), 3),
    ]


def _hash_seed(text: str) -> float:
    return (sum(ord(c) * (i + 1) for i, c in enumerate(text)) % 360) * math.pi / 180.0


class UniverseLayout:
    """Deterministic positions for every entity. Computed once, cached."""

    def __init__(self, universe: UniverseRegistry) -> None:
        self.universe = universe
        self.sector_positions: dict[str, list[float]] = {}
        self.subsector_positions: dict[str, list[float]] = {}
        self.stock_positions: dict[str, list[float]] = {}
        self.build()

    def build(self) -> None:
        viz = get_config().universe.visualization
        galaxy_radius = float(viz.get("galaxy_radius", 260.0))
        vertical = float(viz.get("galaxy_vertical_spread", 70.0))
        sub_radius = float(viz.get("subsector_cluster_radius", 34.0))
        stock_radius = float(viz.get("stock_cluster_radius", 13.0))

        sector_ids = sorted(self.universe.sectors)
        for s_index, sector_id in enumerate(sector_ids):
            centre = _sector_position(s_index, len(sector_ids), galaxy_radius, vertical)
            self.sector_positions[sector_id] = centre

            subsectors = self.universe.subsectors_of(sector_id)
            for sub_index, subsector in enumerate(subsectors):
                offset = _offset(
                    sub_index, len(subsectors), sub_radius, _hash_seed(subsector)
                )
                sub_centre = [centre[i] + offset[i] for i in range(3)]
                self.subsector_positions[f"{sector_id}:{subsector}"] = [
                    round(v, 3) for v in sub_centre
                ]

                stocks = sorted(
                    self.universe.by_subsector(sector_id, subsector), key=lambda s: s.ticker
                )
                for st_index, stock in enumerate(stocks):
                    star_offset = _offset(
                        st_index, len(stocks), stock_radius, _hash_seed(stock.ticker)
                    )
                    self.stock_positions[stock.ticker] = [
                        round(sub_centre[i] + star_offset[i], 3) for i in range(3)
                    ]


def _orbit_speed(volume_ratio: float) -> float:
    """Volume -> orbital velocity. Restrained so heavy names do not create chaos."""
    viz = get_config().universe.visualization
    lo = float(viz.get("orbit_speed_min", 0.02))
    hi = float(viz.get("orbit_speed_max", 0.18))
    # Compress with a log so a 10x volume day is not a 10x speed.
    t = max(0.0, min(1.0, math.log10(max(volume_ratio, 0.1) + 0.1) / math.log10(5.0)))
    return round(lo + t * (hi - lo), 4)


def _intensity(change_pct: float) -> float:
    """Price movement -> brightness, 0-1 centred on 0.5 for flat.

    Deliberately not a red/green ramp: colour alone would be inaccessible and
    emotionally loud (spec section 49).
    """
    # tanh keeps a -15% day from saturating the whole scene.
    return round(0.5 + 0.5 * math.tanh(change_pct * 12.0), 4)


def _pulse_band(score: float) -> str | None:
    viz = get_config().universe.visualization
    bands = viz.get("pulse_bands", {})
    for name in ("strong", "moderate", "subtle"):
        window = bands.get(name)
        if window and float(window[0]) <= score <= float(window[1]):
            return name
    return None


def build_universe_payload(
    universe: UniverseRegistry,
    layout: UniverseLayout,
    quotes: dict[str, Quote],
    technicals: dict[str, TechnicalSnapshot],
    signals: list[Signal],
    positions: list[Position],
    politicals: dict[str, PoliticalSnapshot],
    watchlist: list[str],
    sector_regimes: list[Any] | None = None,
) -> dict[str, Any]:
    best_signal: dict[str, Signal] = {}
    for signal in signals:
        current = best_signal.get(signal.ticker)
        if current is None or signal.score.total > current.score.total:
            best_signal[signal.ticker] = signal

    held = {p.ticker.upper(): p for p in positions}
    watched = {t.upper() for t in watchlist}

    entities: list[dict[str, Any]] = []
    for stock in universe.renderable():
        ticker = stock.ticker
        quote = quotes.get(ticker)
        technical = technicals.get(ticker)
        signal = best_signal.get(ticker)
        political = politicals.get(ticker)
        position = held.get(ticker)

        # Fall back to the last completed session when no live quote exists.
        # A closed or unsubscribed name still shows its last known state rather
        # than rendering as flat and dead (spec section 61).
        if quote is not None:
            change = quote.change_pct
            price = quote.last
            live = True
        elif technical is not None:
            change = technical.change_pct
            price = technical.close
            live = False
        else:
            change, price, live = 0.0, None, False
        volume_ratio = technical.volume_ratio if technical else 1.0

        entity: dict[str, Any] = {
            "id": ticker,
            "type": "stock",
            "name": stock.name,
            "sector": stock.sector,
            "subsector": stock.subsector,
            "position": layout.stock_positions.get(ticker, [0.0, 0.0, 0.0]),
            "size": universe.size_for(ticker),
            "orbit_speed": _orbit_speed(volume_ratio),
            "intensity": _intensity(change),
            "price_change": round(change, 5),
            "volume_ratio": round(volume_ratio, 3),
            "price": round(price, 4) if price else None,
            "live": live,
            "watchlist": ticker in watched,
        }

        if signal is not None:
            entity["signal"] = {
                "active": True,
                "score": signal.confidence,
                "strategy": signal.strategy_id,
                "executable": signal.execution.allowed,
                "pulse": _pulse_band(signal.score.total),
            }
        if position is not None:
            entity["portfolio"] = {
                "held": True,
                # P&L reactivity is subtle by design: a gentle warmth, not a
                # flashing red/green alarm (spec section 54).
                "pnl_pct": position.unrealized_pnl_pct,
                "warmth": round(
                    0.5 + 0.5 * math.tanh(position.unrealized_pnl_pct * 8.0), 4
                ),
            }
        has_political = political is not None and (
            political.purchases_30d or political.distinct_politicians_180d
        )
        if has_political:
            entity["political"] = {
                "active": True,
                "count": political.distinct_politicians_30d or political.purchases_30d,
                "consensus": political.consensus_score,
                "purchases": political.purchases_30d,
                "sales": political.sales_30d,
            }
        entities.append(entity)

    sectors = []
    for sector_id, sector in sorted(universe.sectors.items()):
        regime = next(
            (s for s in (sector_regimes or []) if s.sector_id == sector_id), None
        )
        sectors.append(
            {
                "id": sector_id,
                "type": "sector",
                "label": sector.label,
                "short": sector.short,
                "hue": sector.hue,
                "position": layout.sector_positions.get(sector_id, [0.0, 0.0, 0.0]),
                "member_count": len(universe.by_sector(sector_id)),
                "performance": round(regime.session_performance, 5) if regime else 0.0,
                "relative_strength": round(regime.relative_strength, 5) if regime else 0.0,
                "rs_label": regime.rs_label if regime else "NEUTRAL",
                "breadth": regime.breadth if regime else 0.0,
                "regime": regime.regime.value if regime else "NEUTRAL",
                "news_sentiment": round(regime.news_sentiment, 4) if regime else 0.0,
                "signal_count": regime.signal_count if regime else 0,
                "recommended_strategy": regime.recommended_strategy if regime else None,
            }
        )

    subsectors = [
        {
            "id": sub_id,
            "type": "subsector",
            "label": sub.label,
            "sector": sub.sector_id,
            "position": layout.subsector_positions.get(sub_id, [0.0, 0.0, 0.0]),
            "member_count": len(universe.by_subsector(sub.sector_id, sub.label)),
        }
        for sub_id, sub in sorted(universe.subsectors.items())
    ]

    return {
        "entities": entities,
        "sectors": sectors,
        "subsectors": subsectors,
        "flows": build_flows(sector_regimes or []),
    }


def build_flows(sector_regimes: list[Any]) -> list[dict[str, Any]]:
    """Sector-rotation arcs - the 5% flowfield layer (spec section 51).

    This infers rotation from relative strength. It is NOT institutional
    capital-flow data, and the payload says so explicitly so the UI cannot imply
    otherwise.
    """
    viz = get_config().universe.visualization
    flow_cfg = viz.get("flow", {})
    threshold = float(flow_cfg.get("min_rotation_strength", 0.25))
    max_arcs = int(flow_cfg.get("max_arcs", 12))

    if len(sector_regimes) < 2:
        return []

    ranked = sorted(sector_regimes, key=lambda s: s.relative_strength, reverse=True)
    leaders = [s for s in ranked if s.relative_strength > 0][:4]
    laggards = [s for s in reversed(ranked) if s.relative_strength < 0][:4]

    arcs: list[dict[str, Any]] = []
    for laggard in laggards:
        for leader in leaders:
            spread = leader.relative_strength - laggard.relative_strength
            # Normalize the spread onto 0-1; 4% is a decisive rotation.
            strength = min(1.0, spread / 0.04)
            if strength < threshold:
                continue
            arcs.append(
                {
                    "from": laggard.sector_id,
                    "to": leader.sector_id,
                    "strength": round(strength, 4),
                    "inferred": True,
                    "basis": "relative strength spread, not observed capital flow",
                }
            )
    arcs.sort(key=lambda a: a["strength"], reverse=True)
    return arcs[:max_arcs]
