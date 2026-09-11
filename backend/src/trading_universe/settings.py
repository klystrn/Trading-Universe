"""Process-level settings from environment variables.

Everything here is a *deployment* concern. Trading behaviour lives in the YAML
files under ``config/`` so it can be changed from the UI without a restart.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from trading_universe.domain.enums import DataMode, OperatingMode


def _find_repo_root() -> Path:
    """Walk up from this file until we find the directory holding ``config/``."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "config" / "risk.yaml").exists():
            return parent
    # Fall back to three levels up (src/trading_universe -> src -> backend -> repo)
    return here.parents[3]


REPO_ROOT = _find_repo_root()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Safety interlocks (spec 22.3) -------------------------------------
    # Two independent variables, both of which must be set, plus a UI state and
    # a Moomoo trading unlock. Deliberately difficult to enable accidentally.
    trading_env: str = Field(default="PAPER", alias="TRADING_ENV")
    allow_real_orders: bool = Field(default=False, alias="ALLOW_REAL_ORDERS")

    operating_mode: OperatingMode = Field(
        default=OperatingMode.ADVISORY, alias="TU_OPERATING_MODE"
    )
    data_mode: DataMode = Field(default=DataMode.DEMO, alias="TU_DATA_MODE")

    # --- Moomoo -------------------------------------------------------------
    moomoo_host: str = Field(default="127.0.0.1", alias="MOOMOO_HOST")
    moomoo_port: int = Field(default=11111, alias="MOOMOO_PORT")
    moomoo_trade_pwd: str = Field(default="", alias="MOOMOO_TRADE_PWD")
    moomoo_paper_account_id: str = Field(default="", alias="MOOMOO_PAPER_ACCOUNT_ID")

    # --- External APIs ------------------------------------------------------
    sec_user_agent: str = Field(
        default="TradingUniverse/0.1 (contact-not-configured)", alias="SEC_USER_AGENT"
    )
    marketaux_api_key: str = Field(default="", alias="MARKETAUX_API_KEY")

    # --- Sentiment ----------------------------------------------------------
    sentiment_engine: str = Field(default="lexicon", alias="TU_SENTIMENT_ENGINE")

    # --- Storage ------------------------------------------------------------
    database_url: str = Field(default="", alias="TU_DATABASE_URL")

    # --- Server -------------------------------------------------------------
    api_host: str = Field(default="127.0.0.1", alias="TU_API_HOST")
    api_port: int = Field(default=8000, alias="TU_API_PORT")
    cors_origins: str = Field(default="http://localhost:3000", alias="TU_CORS_ORIGINS")

    # --- Paper broker seed ---------------------------------------------------
    paper_starting_cash: float = Field(default=10000.0, alias="TU_PAPER_STARTING_CASH")

    @field_validator("trading_env")
    @classmethod
    def _normalise_env(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in ("PAPER", "REAL"):
            raise ValueError("TRADING_ENV must be PAPER or REAL")
        return v

    @field_validator("sentiment_engine")
    @classmethod
    def _normalise_engine(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("lexicon", "finbert"):
            raise ValueError("TU_SENTIMENT_ENGINE must be 'lexicon' or 'finbert'")
        return v

    # --- Derived ------------------------------------------------------------
    @property
    def repo_root(self) -> Path:
        return REPO_ROOT

    @property
    def config_dir(self) -> Path:
        return REPO_ROOT / "config"

    @property
    def data_dir(self) -> Path:
        return REPO_ROOT / "data"

    @property
    def db_path(self) -> Path:
        return REPO_ROOT / "db" / "trading.sqlite"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.db_path}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def real_orders_permitted(self) -> bool:
        """Both interlocks must agree. This is the *environment* gate only; the
        execution engine additionally requires LIVE_AUTO mode, an explicit UI
        arming state, and a Moomoo trading unlock."""
        return self.trading_env == "REAL" and self.allow_real_orders

    @property
    def is_paper(self) -> bool:
        return not self.real_orders_permitted


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    """Drop the cache - used by tests and by the /system/reload endpoint."""
    get_settings.cache_clear()
    return get_settings()


# Guard against the classic accident: a stray REAL in the shell environment while
# the operator believes they are on paper. We do not raise (that would make the
# app unbootable) but we make it impossible to miss.
def real_order_warning() -> str | None:
    s = get_settings()
    if s.real_orders_permitted:
        return (
            "TRADING_ENV=REAL and ALLOW_REAL_ORDERS=true. Real-money order "
            "construction is environment-permitted. LIVE_AUTO mode and UI arming "
            "are still required before any order is sent."
        )
    if os.environ.get("TRADING_ENV", "").upper() == "REAL":
        return "TRADING_ENV=REAL but ALLOW_REAL_ORDERS is false - real orders blocked."
    return None
