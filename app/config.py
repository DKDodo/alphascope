"""Application configuration loaded from environment variables / .env file."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration. Defaults keep the app runnable with zero setup:
    SQLite database, mock market data provider, live trading forced off.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: str = Field(default="development", validation_alias="ALPHASCOPE_ENV")
    market_data_provider: Literal["mock", "massive"] = Field(
        default="mock", validation_alias="MARKET_DATA_PROVIDER"
    )
    massive_api_key: str | None = Field(default=None, validation_alias="MASSIVE_API_KEY")

    database_url: str = Field(
        default="sqlite:///./alphascope.db", validation_alias="DATABASE_URL"
    )
    redis_url: str | None = Field(default=None, validation_alias="REDIS_URL")

    paper_trading_only: bool = Field(default=True, validation_alias="PAPER_TRADING_ONLY")
    live_trading_enabled: bool = Field(default=False, validation_alias="LIVE_TRADING_ENABLED")

    scanner_interval_seconds: float = Field(
        default=5.0, validation_alias="SCANNER_INTERVAL_SECONDS"
    )
    mock_tick_interval_seconds: float = Field(
        default=1.0, validation_alias="MOCK_TICK_INTERVAL_SECONDS"
    )
    mock_random_seed: int | None = Field(default=42, validation_alias="MOCK_RANDOM_SEED")

    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    initial_paper_cash: float = Field(
        default=100_000.0, validation_alias="INITIAL_PAPER_CASH"
    )

    bist_enabled: bool = Field(default=True, validation_alias="BIST_ENABLED")
    bist_symbols: str = Field(
        default=(
            # Verified against the live BIST 30 index composition on
            # 2026-09-07 (cross-checked via TradingView + Midas). Index
            # membership is reviewed quarterly by Borsa İstanbul — refresh
            # this list periodically, or override via .env, so it doesn't
            # silently drift from the real index over time.
            "AEFES,AKBNK,ASELS,ASTOR,BIMAS,DSTKF,EKGYO,ENKAI,EREGL,FROTO,"
            "GARAN,GUBRF,ISCTR,KCHOL,KRDMD,MGROS,PETKM,PGSUS,SAHOL,SASA,"
            "SISE,TAVHL,TCELL,THYAO,TOASO,TRALT,TTKOM,TUPRS,VAKBN,YKBNK"
        ),
        validation_alias="BIST_SYMBOLS",
    )
    bist_poll_interval_seconds: float = Field(
        default=60.0, validation_alias="BIST_POLL_INTERVAL_SECONDS"
    )
    bist_initial_paper_cash: float = Field(
        default=1_000_000.0, validation_alias="BIST_INITIAL_PAPER_CASH"
    )

    @property
    def bist_symbol_list(self) -> list[str]:
        return [s.strip().upper() for s in self.bist_symbols.split(",") if s.strip()]

    news_enabled: bool = Field(default=True, validation_alias="NEWS_ENABLED")
    news_poll_interval_seconds: float = Field(
        default=900.0, validation_alias="NEWS_POLL_INTERVAL_SECONDS"
    )
    news_max_items_per_symbol: int = Field(
        default=8, validation_alias="NEWS_MAX_ITEMS_PER_SYMBOL"
    )

    autotrader_tick_interval_seconds: float = Field(
        default=30.0, validation_alias="AUTOTRADER_TICK_INTERVAL_SECONDS"
    )

    @field_validator("live_trading_enabled")
    @classmethod
    def _live_trading_must_stay_disabled(cls, value: bool) -> bool:
        # AlphaScope has no order-execution code path at all. This validator is a
        # second line of defense: even a misconfigured .env cannot flip this on.
        if value:
            raise ValueError(
                "LIVE_TRADING_ENABLED must be false. AlphaScope does not implement "
                "real order execution; this build is analysis/paper-trading only."
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
