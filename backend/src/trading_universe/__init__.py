"""Trading Universe - a swing-trading bot whose interface is a navigable financial universe.

Architectural contract (spec section 4): the seven layers below are separate, and
the dependency arrows only ever point downward.

    data collection -> feature generation -> strategy logic -> signal scoring
    -> risk validation -> order execution -> analytics/visualization

A strategy never places an order. A strategy emits a normalized :class:`Signal`;
the :class:`RiskEngine` alone decides whether that signal may become an order.
"""

__version__ = "0.1.0"
