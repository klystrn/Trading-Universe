"""Live trading gate (spec section 22.3).

The live path is intentionally difficult to enable accidentally. Four
independent conditions must all hold before a real order can even be
constructed, and they are checked here rather than scattered through the code:

1. ``TRADING_ENV=REAL``
2. ``ALLOW_REAL_ORDERS=true``
3. operating mode is ``LIVE_AUTO``
4. the UI has explicitly armed automatic execution this session

Moomoo's own trading unlock is a fifth gate enforced inside :class:`MoomooBroker`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from trading_universe.domain.enums import OperatingMode
from trading_universe.execution.broker_base import BrokerError
from trading_universe.execution.moomoo import MoomooBroker
from trading_universe.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LiveGateResult:
    permitted: bool
    failures: list[str]

    def raise_if_blocked(self) -> None:
        if not self.permitted:
            raise BrokerError("live trading blocked: " + "; ".join(self.failures))


def check_live_gates(operating_mode: OperatingMode, ui_armed: bool) -> LiveGateResult:
    settings = get_settings()
    failures: list[str] = []
    if settings.trading_env != "REAL":
        failures.append("TRADING_ENV is not REAL")
    if not settings.allow_real_orders:
        failures.append("ALLOW_REAL_ORDERS is not true")
    if operating_mode is not OperatingMode.LIVE_AUTO:
        failures.append(f"operating mode is {operating_mode.value}, not LIVE_AUTO")
    if not ui_armed:
        failures.append("automatic execution has not been armed in the UI")
    return LiveGateResult(permitted=not failures, failures=failures)


class LiveBroker(MoomooBroker):
    """A Moomoo broker bound to the real account, constructible only when every
    gate passes."""

    name = "moomoo-live"

    def __init__(self, operating_mode: OperatingMode, ui_armed: bool) -> None:
        gate = check_live_gates(operating_mode, ui_armed)
        gate.raise_if_blocked()
        logger.warning(
            "LiveBroker constructed - REAL MONEY ORDERS ARE NOW POSSIBLE. "
            "Every safety gate passed: TRADING_ENV=REAL, ALLOW_REAL_ORDERS=true, "
            "mode=LIVE_AUTO, UI armed."
        )
        super().__init__(paper=False)

    def place_order(self, order):  # type: ignore[override]
        # Re-check at the moment of the order, not only at construction: a kill
        # switch or mode change between the two must still stop it.
        settings = get_settings()
        if not settings.real_orders_permitted:
            raise BrokerError("real orders are no longer permitted by the environment")
        order.paper = False
        return super().place_order(order)
