"""US equity session classification (spec section 61)."""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from trading_universe.config import get_config
from trading_universe.domain.enums import Session

# US market holidays are not modelled in V1; a closed day simply presents as a
# weekend-equivalent CLOSED session once the live feed stops updating.
_WEEKEND = (5, 6)


def _parse(hhmm: str) -> time:
    hour, minute = hhmm.split(":")
    return time(int(hour), int(minute))


def current_session(now: datetime | None = None) -> Session:
    cfg = get_config().universe
    sessions = cfg.get("sessions", {}) or {}
    tz = ZoneInfo(sessions.get("timezone", "America/New_York"))
    now = (now or datetime.now(UTC)).astimezone(tz)

    if now.weekday() in _WEEKEND:
        return Session.CLOSED

    local = now.time()
    for name, key in (
        (Session.PRE_MARKET, "pre_market"),
        (Session.REGULAR, "regular"),
        (Session.AFTER_HOURS, "after_hours"),
    ):
        window = sessions.get(key)
        if not window:
            continue
        start, end = _parse(window[0]), _parse(window[1])
        if start <= local < end:
            return name
    return Session.CLOSED


def is_regular_session(now: datetime | None = None) -> bool:
    return current_session(now) is Session.REGULAR


def session_permits_auto_execution(now: datetime | None = None) -> bool:
    allowed = get_config().risk.get("sessions.allow_auto_execution_in", ["REGULAR"])
    return current_session(now).value in allowed


def session_permits_signal_generation(now: datetime | None = None) -> bool:
    allowed = get_config().risk.get(
        "sessions.allow_signal_generation_in", ["PRE_MARKET", "REGULAR", "AFTER_HOURS"]
    )
    return current_session(now).value in allowed
