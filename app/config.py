"""Application configuration loaded from environment variables / .env file."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration. Defaults keep the app runnable with zero setup:
    SQLite database, real (delayed) Yahoo Finance market data, live trading
    forced off.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: str = Field(default="development", validation_alias="ALPHASCOPE_ENV")
    # "yfinance" (real, delayed Yahoo Finance data — the same provider BIST
    # already uses) is the default for both tabs. "mock" (synthetic random-walk
    # data, no network) stays available as an explicit opt-in for offline
    # dev/testing. "massive" requires MASSIVE_API_KEY, else falls back to yfinance.
    market_data_provider: Literal["mock", "massive", "yfinance"] = Field(
        default="yfinance", validation_alias="MARKET_DATA_PROVIDER"
    )
    massive_api_key: str | None = Field(default=None, validation_alias="MASSIVE_API_KEY")

    database_url: str = Field(
        default="sqlite:///./alphascope.db", validation_alias="DATABASE_URL"
    )
    redis_url: str | None = Field(default=None, validation_alias="REDIS_URL")

    paper_trading_only: bool = Field(default=True, validation_alias="PAPER_TRADING_ONLY")
    live_trading_enabled: bool = Field(default=False, validation_alias="LIVE_TRADING_ENABLED")

    # Free-tier hosts (e.g. Render's 0.1 CPU / 512MB plan) have very little
    # headroom — recomputing every symbol's indicators every few seconds
    # was found in production to starve the event loop badly enough that
    # the host restarts the instance (which looks like a running simulation
    # randomly "stopping"). These defaults trade a bit of freshness for
    # actually staying up; override via .env for a beefier host.
    scanner_interval_seconds: float = Field(
        default=20.0, validation_alias="SCANNER_INTERVAL_SECONDS"
    )
    mock_tick_interval_seconds: float = Field(
        default=3.0, validation_alias="MOCK_TICK_INTERVAL_SECONDS"
    )
    mock_random_seed: int | None = Field(default=42, validation_alias="MOCK_RANDOM_SEED")

    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    # Starting balance for the manual ("Kağıt Portföy") paper portfolio the
    # user trades by hand -- separate from AutoTrader, whose own starting
    # cash is chosen per-run from the simulation start form instead.
    initial_paper_cash: float = Field(
        default=10_000.0, validation_alias="INITIAL_PAPER_CASH"
    )

    # Global (ABD) tab — real, delayed Yahoo Finance data (no suffix needed
    # for US tickers). Override GLOBAL_SYMBOLS via .env to track a different
    # list. Default is ~50 large/liquid, well-known US companies spread
    # across sectors (tech, finance, healthcare, consumer, energy, telecom,
    # industrials) rather than concentrated in one sector — same spirit as
    # BIST_SYMBOLS, though this isn't tracking an official index the way
    # "BIST 30" is, just a broad, recognizable selection.
    global_symbols: str = Field(
        default=(
            "AAPL,MSFT,NVDA,GOOGL,AMZN,META,AMD,ORCL,CRM,ADBE,INTC,CSCO,"
            "NFLX,DIS,TMUS,JPM,V,MA,BAC,WFC,GS,MS,"
            "JNJ,UNH,PFE,ABBV,MRK,"
            "WMT,PG,KO,PEP,COST,HD,MCD,NKE,"
            "TSLA,BA,CAT,GE,"
            "XOM,CVX,COP,"
            "VZ,T,"
            "UBER,PYPL,SBUX,LOW,TXN,QCOM"
        ),
        validation_alias="GLOBAL_SYMBOLS",
    )
    global_poll_interval_seconds: float = Field(
        default=60.0, validation_alias="GLOBAL_POLL_INTERVAL_SECONDS"
    )

    @property
    def global_symbol_list(self) -> list[str]:
        return [s.strip().upper() for s in self.global_symbols.split(",") if s.strip()]

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

    # Crypto tab — same YFinanceProvider as Global/BIST (yfinance covers
    # crypto via a "-USD" suffix, e.g. BTC-USD), no separate exchange
    # integration needed. Trades 24/7, so unlike BIST/Global there's no
    # "market closed" excuse for stale data — see SignalEngine's staleness check.
    crypto_enabled: bool = Field(default=True, validation_alias="CRYPTO_ENABLED")
    crypto_symbols: str = Field(
        default="BTC,ETH,BNB,SOL,XRP,ADA,DOGE,AVAX",
        validation_alias="CRYPTO_SYMBOLS",
    )
    crypto_poll_interval_seconds: float = Field(
        default=60.0, validation_alias="CRYPTO_POLL_INTERVAL_SECONDS"
    )
    crypto_initial_paper_cash: float = Field(
        default=10_000.0, validation_alias="CRYPTO_INITIAL_PAPER_CASH"
    )

    @property
    def crypto_symbol_list(self) -> list[str]:
        return [s.strip().upper() for s in self.crypto_symbols.split(",") if s.strip()]

    # Optional opt-in for real-time (push, not polled) data via Binance's
    # free public WebSocket (no API key/account needed), instead of the
    # default (60s-polled, ~15-20min-delayed) YFinanceProvider every other
    # tab uses. Independent of MARKET_DATA_PROVIDER, which only affects the
    # Global (ABD) tab (see _build_global_provider) -- defaults to
    # "yfinance" so nobody's crypto tab silently switches feeds without
    # opting in via .env.
    crypto_market_data_provider: Literal["yfinance", "binance"] = Field(
        default="yfinance", validation_alias="CRYPTO_MARKET_DATA_PROVIDER"
    )
    # Quote asset Binance pairs are built against (e.g. CRYPTO_SYMBOLS'
    # "BTC" -> "BTCUSDT"). A single global setting, not per-symbol: USDT
    # already has the deepest/most liquid market for every symbol in the
    # default CRYPTO_SYMBOLS list.
    binance_quote_asset: str = Field(default="USDT", validation_alias="BINANCE_QUOTE_ASSET")

    news_enabled: bool = Field(default=True, validation_alias="NEWS_ENABLED")
    news_poll_interval_seconds: float = Field(
        default=900.0, validation_alias="NEWS_POLL_INTERVAL_SECONDS"
    )
    news_max_items_per_symbol: int = Field(
        default=8, validation_alias="NEWS_MAX_ITEMS_PER_SYMBOL"
    )

    autotrader_tick_interval_seconds: float = Field(
        default=60.0, validation_alias="AUTOTRADER_TICK_INTERVAL_SECONDS"
    )

    # Desktop-only Windows toast notifications for AutoTrader events (new
    # position, drawdown breaker paused) -- see app/notifications/notifier.py.
    # Ignored entirely on the web deploy, which has no desktop to notify.
    notifications_enabled: bool = Field(default=True, validation_alias="NOTIFICATIONS_ENABLED")

    # How often to check for due signal-performance checkpoints (5/10/20
    # days after a signal change). These are day-scale, so hourly is plenty.
    signal_tracking_interval_seconds: float = Field(
        default=3_600.0, validation_alias="SIGNAL_TRACKING_INTERVAL_SECONDS"
    )

    fundamentals_poll_interval_seconds: float = Field(
        default=21_600.0, validation_alias="FUNDAMENTALS_POLL_INTERVAL_SECONDS"
    )

    # How often to refresh each symbol's daily-bar (EMA50/EMA200) trend
    # direction, used by AutoTrader as a multi-timeframe confirmation gate.
    # Day-scale like fundamentals, so a slow poll is plenty.
    daily_trend_poll_interval_seconds: float = Field(
        default=21_600.0, validation_alias="DAILY_TREND_POLL_INTERVAL_SECONDS"
    )

    # Matches the dashboard's own 60s macro-strip refresh (app.js) so the
    # displayed numbers actually change on most refreshes instead of only
    # every few cycles.
    macro_poll_interval_seconds: float = Field(
        default=60.0, validation_alias="MACRO_POLL_INTERVAL_SECONDS"
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
