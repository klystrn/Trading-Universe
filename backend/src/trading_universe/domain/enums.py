"""Enumerations shared across the platform."""

from __future__ import annotations

from enum import StrEnum


class OperatingMode(StrEnum):
    """Spec section 22. The platform supports three modes from the beginning."""

    ADVISORY = "ADVISORY"
    PAPER_AUTO = "PAPER_AUTO"
    LIVE_AUTO = "LIVE_AUTO"


class DataMode(StrEnum):
    """Where market/news/political data comes from."""

    DEMO = "DEMO"
    LIVE = "LIVE"


class Session(StrEnum):
    """Spec section 61. Trading rules may differ by session."""

    PRE_MARKET = "PRE_MARKET"
    REGULAR = "REGULAR"
    AFTER_HOURS = "AFTER_HOURS"
    CLOSED = "CLOSED"


class MarketRegime(StrEnum):
    """Spec section 7. Rule-based and explainable; no statistical learning in V1."""

    STRONG_BULL = "STRONG_BULL"
    BULL = "BULL"
    NEUTRAL = "NEUTRAL"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    CORRECTION = "CORRECTION"
    RECOVERY = "RECOVERY"
    RISK_OFF = "RISK_OFF"


class StrategyKind(StrEnum):
    """Determines which scoring weight set and score threshold applies."""

    STANDARD = "standard"
    POLITICAL = "political"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ExecutionSource(StrEnum):
    """How an order came to exist - needed by the trade log (spec 36)."""

    AUTO = "AUTO"
    MANUAL = "MANUAL"
    RECOMMENDED_ACCEPTED = "RECOMMENDED_ACCEPTED"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


class TradeResult(StrEnum):
    OPEN = "OPEN"
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"


class FreshnessStatus(StrEnum):
    """Spec section 30. A stale value must never silently masquerade as live."""

    LIVE = "LIVE"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class TransactionType(StrEnum):
    PURCHASE = "PURCHASE"
    SALE = "SALE"
    SALE_PARTIAL = "SALE_PARTIAL"
    SALE_FULL = "SALE_FULL"
    EXCHANGE = "EXCHANGE"


class Chamber(StrEnum):
    HOUSE = "HOUSE"
    SENATE = "SENATE"


class PoliticalOwner(StrEnum):
    """Spec section 14: track member / spouse separately where possible."""

    SELF = "SELF"
    SPOUSE = "SPOUSE"
    DEPENDENT = "DEPENDENT"
    JOINT = "JOINT"
    UNKNOWN = "UNKNOWN"


class CatalystType(StrEnum):
    """Spec section 10 - valid catalysts for S2."""

    EARNINGS = "EARNINGS"
    GUIDANCE = "GUIDANCE"
    CONTRACT = "CONTRACT"
    ACQUISITION = "ACQUISITION"
    PRODUCT = "PRODUCT"
    REGULATORY = "REGULATORY"
    MATERIAL_8K = "MATERIAL_8K"
    MANAGEMENT = "MANAGEMENT"
    OTHER = "OTHER"


class RejectionReason(StrEnum):
    """Machine-readable risk rejections (spec section 76).

    The UI explains rejected trades rather than silently dropping them, so every
    rejection path must map onto one of these.
    """

    KILL_SWITCH_ENGAGED = "KILL_SWITCH_ENGAGED"
    SCORE_BELOW_THRESHOLD = "SCORE_BELOW_THRESHOLD"
    REWARD_RISK_BELOW_MINIMUM = "REWARD_RISK_BELOW_MINIMUM"
    MAX_OPEN_POSITIONS_REACHED = "MAX_OPEN_POSITIONS_REACHED"
    MAX_NEW_TRADES_PER_DAY_REACHED = "MAX_NEW_TRADES_PER_DAY_REACHED"
    DUPLICATE_TICKER_POSITION = "DUPLICATE_TICKER_POSITION"
    DUPLICATE_ORDER = "DUPLICATE_ORDER"
    AVERAGING_DOWN_BLOCKED = "AVERAGING_DOWN_BLOCKED"
    SHORT_NOT_ALLOWED = "SHORT_NOT_ALLOWED"
    INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    PRICE_BELOW_MINIMUM = "PRICE_BELOW_MINIMUM"
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    NEWS_DATA_STALE = "NEWS_DATA_STALE"
    REQUIRED_SOURCE_UNAVAILABLE = "REQUIRED_SOURCE_UNAVAILABLE"
    SESSION_NOT_PERMITTED = "SESSION_NOT_PERMITTED"
    LOSS_STREAK_PAUSE = "LOSS_STREAK_PAUSE"
    STRATEGY_NOT_ACTIVE = "STRATEGY_NOT_ACTIVE"
    STRATEGY_DISABLED = "STRATEGY_DISABLED"
    POSITION_VALUE_TOO_SMALL = "POSITION_VALUE_TOO_SMALL"
    ENTRY_DRIFTED = "ENTRY_DRIFTED"
    INVALID_STOP = "INVALID_STOP"
    REAL_ORDERS_NOT_ENABLED = "REAL_ORDERS_NOT_ENABLED"
    BROKER_UNAVAILABLE = "BROKER_UNAVAILABLE"
