"""Position sizing (spec section 19).

The $150 limit is MAXIMUM CAPITAL DEPLOYED, not maximum loss. That distinction
matters: a $150 position with a 4% technical stop risks $6, not $150.

    quantity = max_position_value / entry_price

Fractional shares are used where supported; otherwise the quantity is floored to
whole shares, which can leave the position below the cap (never above).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SizingResult:
    quantity: float
    position_value: float
    risk_amount: float
    fractional_used: bool
    note: str | None = None

    @property
    def viable(self) -> bool:
        return self.quantity > 0


def size_position(
    entry: float,
    stop: float,
    max_position_value: float,
    allow_fractional: bool,
    min_notional: float = 5.0,
    fractional_precision: int = 4,
) -> SizingResult:
    """Size a long position against the capital cap."""
    if entry <= 0:
        return SizingResult(0.0, 0.0, 0.0, False, "entry price is not positive")
    if stop >= entry:
        return SizingResult(0.0, 0.0, 0.0, False, "stop is not below entry")

    raw_quantity = max_position_value / entry

    if allow_fractional:
        quantity = round(raw_quantity, fractional_precision)
        fractional_used = quantity != int(quantity)
        note = None
    else:
        quantity = float(int(raw_quantity))
        fractional_used = False
        note = (
            f"fractional shares disabled; {raw_quantity:.4f} floored to {quantity:.0f}"
            if quantity != raw_quantity
            else None
        )

    if quantity <= 0:
        return SizingResult(
            0.0, 0.0, 0.0, False,
            f"one share costs ${entry:,.2f}, above the ${max_position_value:,.2f} cap, "
            "and fractional shares are disabled",
        )

    position_value = round(quantity * entry, 4)

    # Rounding up at the last decimal must never breach the cap.
    if position_value > max_position_value:
        step = 10.0 ** (-fractional_precision) if allow_fractional else 1.0
        quantity = round(max(0.0, quantity - step), fractional_precision)
        position_value = round(quantity * entry, 4)

    if position_value < min_notional:
        return SizingResult(
            quantity, position_value, 0.0, fractional_used,
            f"position value ${position_value:,.2f} below the ${min_notional:,.2f} minimum",
        )

    risk_amount = round(quantity * (entry - stop), 4)
    return SizingResult(quantity, position_value, risk_amount, fractional_used, note)
