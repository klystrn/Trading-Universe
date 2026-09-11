"""Strategy registry - the only place strategies are instantiated."""

from __future__ import annotations

from trading_universe.config import get_config
from trading_universe.strategies.base import Strategy
from trading_universe.strategies.catalyst_breakout import FundamentalCatalystBreakout
from trading_universe.strategies.congress_consensus import CongressConsensus
from trading_universe.strategies.congress_purchase import CongressFreshPurchase
from trading_universe.strategies.congress_repeat_buyer import CongressRepeatBuyer
from trading_universe.strategies.momentum_pullback import QualityMomentumPullback
from trading_universe.strategies.oversold_reversal import QualityOversoldReversal
from trading_universe.strategies.value_reclaim import ValueReratingReclaim
from trading_universe.strategies.volatility_squeeze import QualityVolatilitySqueeze

STRATEGY_CLASSES: list[type[Strategy]] = [
    QualityMomentumPullback,
    FundamentalCatalystBreakout,
    QualityOversoldReversal,
    QualityVolatilitySqueeze,
    ValueReratingReclaim,
    CongressFreshPurchase,
    CongressConsensus,
    CongressRepeatBuyer,
]

STRATEGY_BY_ID: dict[str, type[Strategy]] = {cls.id: cls for cls in STRATEGY_CLASSES}


def build_strategies(only_enabled: bool = True) -> dict[str, Strategy]:
    """Instantiate every strategy with its current configuration.

    Called fresh on each scan cycle so UI edits to the YAML take effect without
    a restart.
    """
    cfg = get_config().strategies
    out: dict[str, Strategy] = {}
    for sid, cls in STRATEGY_BY_ID.items():
        strategy_cfg = cfg.strategy(sid)
        if only_enabled and not strategy_cfg.get("enabled", True):
            continue
        out[sid] = cls(strategy_cfg)
    return out


def build_strategy(strategy_id: str) -> Strategy | None:
    cls = STRATEGY_BY_ID.get(strategy_id)
    if cls is None:
        return None
    return cls(get_config().strategies.strategy(strategy_id))


def strategy_labels() -> dict[str, str]:
    return {sid: cls.label for sid, cls in STRATEGY_BY_ID.items()}
