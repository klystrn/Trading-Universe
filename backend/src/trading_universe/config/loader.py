"""Loading, validating, mutating and persisting the YAML configuration."""

from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any

import yaml

from trading_universe.settings import get_settings


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _get_path(data: dict[str, Any], dotted: str) -> Any:
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"config path not found: {dotted}")
        node = node[part]
    return node


def _set_path(data: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    node = data
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value


class _YamlConfig:
    """A single YAML file held in memory with copy-on-write updates."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        with self._lock:
            if self.path.exists():
                loaded = yaml.safe_load(self.path.read_text()) or {}
                if not isinstance(loaded, dict):
                    raise ValueError(f"{self.path} must contain a YAML mapping")
                self._data = loaded
            else:
                self._data = {}

    @property
    def data(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._data)

    def get(self, dotted: str, default: Any = None) -> Any:
        with self._lock:
            try:
                return copy.deepcopy(_get_path(self._data, dotted))
            except KeyError:
                return default

    def set(self, dotted: str, value: Any) -> None:
        with self._lock:
            _set_path(self._data, dotted, value)

    def update(self, patch: dict[str, Any]) -> None:
        """Deep-merge a nested patch."""
        with self._lock:
            self._data = _deep_merge(self._data, patch)

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                yaml.safe_dump(self._data, sort_keys=False, default_flow_style=False)
            )


class RiskConfig(_YamlConfig):
    """Typed accessors for the values the risk engine reads on every decision."""

    @property
    def minimum_reward_risk(self) -> float:
        return float(self.get("minimum_reward_risk", 1.75))

    @property
    def max_position_value(self) -> float:
        return float(self.get("max_position_value", 150.0))

    @property
    def max_new_trades_per_day(self) -> int:
        return int(self.get("max_new_trades_per_day", 3))

    @property
    def max_open_positions(self) -> int:
        return int(self.get("max_open_positions", 5))

    @property
    def allow_fractional_shares(self) -> bool:
        return bool(self.get("allow_fractional_shares", True))

    @property
    def long_only(self) -> bool:
        return bool(self.get("long_only", True))

    @property
    def kill_switch_engaged(self) -> bool:
        return bool(self.get("kill_switch_engaged", False))

    def set_kill_switch(self, engaged: bool, persist: bool = True) -> None:
        self.set("kill_switch_engaged", bool(engaged))
        if persist:
            self.save()

    @property
    def min_score_standard(self) -> float:
        return float(self.get("min_score_standard", 70))

    @property
    def min_score_political(self) -> float:
        return float(self.get("min_score_political", 75))


class StrategyConfig(_YamlConfig):
    def strategy(self, strategy_id: str) -> dict[str, Any]:
        return self.get(f"strategies.{strategy_id}", {}) or {}

    def enabled_strategies(self) -> list[str]:
        strategies = self.get("strategies", {}) or {}
        return [sid for sid, cfg in strategies.items() if cfg.get("enabled", False)]

    def all_strategy_ids(self) -> list[str]:
        return list((self.get("strategies", {}) or {}).keys())

    def weights(self, kind: str) -> dict[str, float]:
        return self.get(f"scoring.{kind}", {}) or {}

    def minimum_score(self, strategy_id: str) -> float:
        cfg = self.strategy(strategy_id)
        if "minimum_score" in cfg:
            return float(cfg["minimum_score"])
        kind = cfg.get("kind", "standard")
        return float(self.get(f"scoring.{kind}.minimum_score", 70))

    def regime_preferences(self, regime: str) -> list[str]:
        return self.get(f"regime_preferences.{regime}", []) or []


class FreshnessConfig(_YamlConfig):
    def source(self, name: str) -> dict[str, Any]:
        return self.get(f"sources.{name}", {}) or {}

    def all_sources(self) -> dict[str, Any]:
        return self.get("sources", {}) or {}

    def requirements(self, strategy_id: str) -> dict[str, list[str]]:
        req = self.get(f"strategy_requirements.{strategy_id}", {}) or {}
        return {
            "required": req.get("required", []) or [],
            "preferred": req.get("preferred", []) or [],
        }


class UniverseConfig(_YamlConfig):
    @property
    def sectors(self) -> list[dict[str, Any]]:
        return self.get("sectors", []) or []

    @property
    def visualization(self) -> dict[str, Any]:
        return self.get("visualization", {}) or {}

    @property
    def tiers(self) -> dict[str, Any]:
        return self.get("tiers", {}) or {}

    @property
    def constituents_path(self) -> Path:
        rel = self.get("constituents_file", "data/constituents.csv")
        return get_settings().repo_root / rel


class ConfigStore:
    """Aggregate handle passed around the application."""

    def __init__(self, config_dir: Path | None = None) -> None:
        base = config_dir or get_settings().config_dir
        self.risk = RiskConfig(base / "risk.yaml")
        self.strategies = StrategyConfig(base / "strategies.yaml")
        self.freshness = FreshnessConfig(base / "freshness.yaml")
        self.universe = UniverseConfig(base / "universe.yaml")

    def reload(self) -> None:
        for cfg in (self.risk, self.strategies, self.freshness, self.universe):
            cfg.reload()

    def save_all(self) -> None:
        for cfg in (self.risk, self.strategies, self.freshness, self.universe):
            cfg.save()

    def as_dict(self) -> dict[str, Any]:
        return {
            "risk": self.risk.data,
            "strategies": self.strategies.data,
            "freshness": self.freshness.data,
            "universe": self.universe.data,
        }


_store: ConfigStore | None = None
_store_lock = threading.Lock()


def get_config() -> ConfigStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = ConfigStore()
    return _store


def reload_config() -> ConfigStore:
    global _store
    with _store_lock:
        _store = ConfigStore()
    return _store
