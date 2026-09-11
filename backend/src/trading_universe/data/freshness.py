"""FreshnessService (spec sections 24, 28, 29, 30).

Trading Universe cannot guarantee that every external source publishes
instantaneously. What it does guarantee is this:

    The bot will never knowingly trade using data older than the defined
    freshness requirement for that strategy.

That guarantee is enforced here and consumed by the RiskEngine. A stale value is
never allowed to silently masquerade as live.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from trading_universe.config import get_config
from trading_universe.domain.enums import FreshnessStatus
from trading_universe.domain.health import FreshnessState


def utcnow() -> datetime:
    return datetime.now(UTC)


class _Observation:
    __slots__ = ("event_time", "received_time", "detail", "available")

    def __init__(
        self,
        event_time: datetime,
        received_time: datetime,
        detail: str | None,
        available: bool,
    ) -> None:
        self.event_time = event_time
        self.received_time = received_time
        self.detail = detail
        self.available = available


class FreshnessService:
    """Tracks the most recent observation per source and grades it against
    the thresholds in ``config/freshness.yaml``."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._obs: dict[str, _Observation] = {}
        # Sources explicitly marked unavailable (connection lost, quota out).
        self._unavailable: dict[str, str] = {}

    # -- recording ----------------------------------------------------------
    def record(
        self,
        source: str,
        event_time: datetime | None = None,
        received_time: datetime | None = None,
        detail: str | None = None,
    ) -> None:
        """Record that ``source`` produced data for an event at ``event_time``."""
        now = utcnow()
        et = event_time or now
        rt = received_time or now
        if et.tzinfo is None:
            et = et.replace(tzinfo=UTC)
        if rt.tzinfo is None:
            rt = rt.replace(tzinfo=UTC)
        with self._lock:
            self._obs[source] = _Observation(et, rt, detail, True)
            self._unavailable.pop(source, None)

    def mark_unavailable(self, source: str, reason: str) -> None:
        with self._lock:
            self._unavailable[source] = reason

    def clear(self) -> None:
        with self._lock:
            self._obs.clear()
            self._unavailable.clear()

    # -- grading ------------------------------------------------------------
    def state(self, source: str, now: datetime | None = None) -> FreshnessState:
        cfg = get_config().freshness.source(source)
        warn = cfg.get("warn_age_seconds")
        mx = cfg.get("max_age_seconds")
        blocking = bool(cfg.get("blocking", False))
        now = now or utcnow()

        with self._lock:
            unavailable_reason = self._unavailable.get(source)
            obs = self._obs.get(source)

        if unavailable_reason is not None:
            return FreshnessState(
                source=source,
                status=FreshnessStatus.UNAVAILABLE,
                warn_age_seconds=warn,
                max_age_seconds=mx,
                blocking=blocking,
                detail=unavailable_reason,
            )
        if obs is None:
            return FreshnessState(
                source=source,
                status=FreshnessStatus.UNAVAILABLE,
                warn_age_seconds=warn,
                max_age_seconds=mx,
                blocking=blocking,
                detail="no observation recorded",
            )

        age = max(0.0, (now - obs.event_time).total_seconds())
        if mx is not None and age > float(mx):
            status = FreshnessStatus.STALE
        elif warn is not None and age > float(warn):
            status = FreshnessStatus.DEGRADED
        elif warn is not None and age <= float(warn) / 2.0:
            status = FreshnessStatus.LIVE
        else:
            status = FreshnessStatus.HEALTHY

        return FreshnessState(
            source=source,
            status=status,
            age_seconds=round(age, 3),
            warn_age_seconds=warn,
            max_age_seconds=mx,
            blocking=blocking,
            last_event_time=obs.event_time,
            last_received_time=obs.received_time,
            detail=obs.detail,
        )

    def all_states(self, now: datetime | None = None) -> list[FreshnessState]:
        sources = set(get_config().freshness.all_sources())
        with self._lock:
            sources |= set(self._obs) | set(self._unavailable)
        return [self.state(s, now) for s in sorted(sources)]

    # -- latency metrics (spec 28) ------------------------------------------
    def latency(self, source: str, now: datetime | None = None) -> dict[str, float | None]:
        now = now or utcnow()
        with self._lock:
            obs = self._obs.get(source)
        if obs is None:
            return {"source_latency": None, "processing_latency": None, "data_age": None}
        return {
            "source_latency": round((obs.received_time - obs.event_time).total_seconds(), 3),
            "processing_latency": None,
            "data_age": round((now - obs.event_time).total_seconds(), 3),
        }

    # -- strategy gating ----------------------------------------------------
    def evaluate_strategy(
        self, strategy_id: str, now: datetime | None = None
    ) -> tuple[bool, list[str], dict[str, FreshnessState]]:
        """Can ``strategy_id`` produce an *executable* signal right now?

        Returns ``(ok, blocking_reasons, states_by_source)``. A required source
        that is STALE or UNAVAILABLE blocks. A preferred source that degrades
        does not block but is reported.
        """
        reqs = get_config().freshness.requirements(strategy_id)
        now = now or utcnow()
        states: dict[str, FreshnessState] = {}
        blockers: list[str] = []

        for source in reqs["required"]:
            st = self.state(source, now)
            states[source] = st
            if st.status in (FreshnessStatus.STALE, FreshnessStatus.UNAVAILABLE):
                blockers.append(source)
        for source in reqs["preferred"]:
            states[source] = self.state(source, now)

        return (not blockers, blockers, states)

    def required_sources(self) -> set[str]:
        """Sources at least one enabled strategy actually depends on."""
        cfg = get_config()
        required: set[str] = set()
        for strategy_id in cfg.strategies.enabled_strategies():
            required.update(cfg.freshness.requirements(strategy_id)["required"])
        return required

    def overall_status(self, now: datetime | None = None) -> FreshnessStatus:
        states = self.all_states(now)
        if not states:
            return FreshnessStatus.UNAVAILABLE
        # Only sources something depends on can take the system down. A
        # configured-but-unused feed going quiet is worth showing, not worth
        # declaring an outage over.
        required = self.required_sources()
        blocking = [s for s in states if s.blocking and s.source in required]
        if any(s.status is FreshnessStatus.UNAVAILABLE for s in blocking):
            return FreshnessStatus.UNAVAILABLE
        if any(s.status is FreshnessStatus.STALE for s in blocking):
            return FreshnessStatus.STALE
        if any(s.status is FreshnessStatus.DEGRADED for s in states):
            return FreshnessStatus.DEGRADED
        if any(s.status is FreshnessStatus.UNAVAILABLE for s in states):
            return FreshnessStatus.DEGRADED
        if all(s.status is FreshnessStatus.LIVE for s in states):
            return FreshnessStatus.LIVE
        return FreshnessStatus.HEALTHY
