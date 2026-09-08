"""AlphaScope FastAPI application entrypoint.

Flow: Market Data Provider -> Normalizer -> Scanner -> Indicators ->
Signal Engine -> Risk Engine -> FastAPI. Paper trading only; live trading is
not implemented anywhere in this codebase.
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import (
    fundamentals,
    health,
    macro,
    market,
    markets,
    news,
    portfolio,
    risk,
    scanner,
    signals,
    simulation,
)
from app.autotrader.autotrader_service import AutoTraderService
from app.config import Settings, get_settings
from app.core.events import AsyncEventBus
from app.core.exceptions import ProviderNotConfiguredError, RiskCalculationError
from app.core.logging import get_logger, setup_logging
from app.fundamentals.fundamentals_service import FundamentalsService
from app.macro.macro_service import MacroService
from app.market_data.base import BaseMarketDataProvider
from app.market_data.models import MarketEvent
from app.market_data.providers.mock_provider import MockProvider
from app.market_data.providers.yfinance_provider import YFinanceProvider
from app.news.news_service import NewsService
from app.portfolio.paper_portfolio import PaperPortfolio
from app.risk.risk_engine import RiskEngine
from app.scanner import bar_repository
from app.scanner.scanner_engine import ScannerEngine
from app.scanner.universe import Universe
from app.services.market_context import MarketContext
from app.services.market_service import MarketService
from app.services.scanner_service import ScannerService
from app.signals.signal_engine import SignalEngine
from app.storage.database import Database

logger = get_logger(__name__)

# Shown in both markets' macro strips alongside their own market-specific
# indicators (S&P 500/VIX for Global, BIST 100 for BIST) — these four are
# general-reference, not tied to either market specifically.
_COMMON_MACRO_INDICATORS: list[tuple[str, str, str]] = [
    ("EURTRY=X", "Euro/TL", "Euro/TL kuru — genel referans"),
    ("GC=F", "Altın (Ons, $)", "Ons altın fiyatı — güvenli liman varlığı, genel piyasa risk iştahının göstergesi"),
    ("SI=F", "Gümüş (Ons, $)", "Ons gümüş fiyatı — emtia piyasası göstergesi"),
    ("BTC-USD", "Bitcoin ($)", "Bitcoin/USD fiyatı — kripto piyasası risk iştahının göstergesi"),
]


def _build_global_provider(settings: Settings, symbols: list[str]) -> BaseMarketDataProvider:
    if settings.market_data_provider == "massive":
        try:
            from app.market_data.providers.massive_provider import MassiveProvider

            return MassiveProvider(api_key=settings.massive_api_key)
        except ProviderNotConfiguredError as exc:
            logger.warning(
                "massive provider not configured (%s); falling back to yfinance", exc
            )
    if settings.market_data_provider == "mock":
        return MockProvider(
            symbols=symbols,
            tick_interval_seconds=settings.mock_tick_interval_seconds,
            seed=settings.mock_random_seed,
        )
    # Default: real, delayed Yahoo Finance data — same provider/approach as
    # BIST (yf.download(), never the cloud-host-unreliable .info endpoint).
    # US tickers need no suffix.
    return YFinanceProvider(
        symbols=symbols,
        exchange="NASDAQ",
        poll_interval_seconds=settings.global_poll_interval_seconds,
        ticker_suffix="",
    )


def _seed_scanner_from_db(
    scanner_engine: ScannerEngine, db: Database, market_key: str, symbols: list[str]
) -> None:
    """Warm-starts the scanner's rolling indicator window from bars persisted
    on a previous run, so a restart (redeploy, desktop EXE relaunch) doesn't
    reset EMA200/etc. back to zero — see app/scanner/bar_repository.py."""
    total_bars = 0
    for symbol in symbols:
        bars = bar_repository.load_recent_bars(db.session_factory, market_key, symbol)
        for bar in bars:
            scanner_engine.seed_bar(symbol, bar.open, bar.high, bar.low, bar.close, bar.volume)
        total_bars += len(bars)
    if total_bars:
        logger.info(
            "seeded %s scanner with %d persisted bars across %d symbols",
            market_key, total_bars, len(symbols),
        )


def _build_context(
    key: str,
    label: str,
    currency_symbol: str,
    universe: Universe,
    provider: BaseMarketDataProvider,
    settings: Settings,
    starting_cash: float,
    db: Database,
    news_ticker_suffix: str = "",
    macro_indicators: list[tuple[str, str, str]] | None = None,
    note: str | None = None,
) -> MarketContext:
    event_bus: AsyncEventBus[MarketEvent] = AsyncEventBus()
    scanner_engine = ScannerEngine()
    _seed_scanner_from_db(scanner_engine, db, key, universe.symbols)
    signal_engine = SignalEngine(risk_engine=RiskEngine())
    portfolio = PaperPortfolio(starting_cash=starting_cash)

    market_service = MarketService(provider=provider, event_bus=event_bus, symbols=universe.symbols)
    scanner_service = ScannerService(
        event_bus=event_bus,
        scanner_engine=scanner_engine,
        signal_engine=signal_engine,
        portfolio=portfolio,
        scan_interval_seconds=settings.scanner_interval_seconds,
        market_key=key,
        session_factory=db.session_factory,
    )

    news_service = None
    if settings.news_enabled:
        news_service = NewsService(
            symbols=universe.symbols,
            ticker_suffix=news_ticker_suffix,
            poll_interval_seconds=settings.news_poll_interval_seconds,
            max_items_per_symbol=settings.news_max_items_per_symbol,
        )

    autotrader_service = AutoTraderService(
        session_factory=db.session_factory,
        market=key,
        currency_symbol=currency_symbol,
        scanner_service=scanner_service,
        tick_interval_seconds=settings.autotrader_tick_interval_seconds,
    )

    fundamentals_service = FundamentalsService(
        symbols=universe.symbols,
        scanner_engine=scanner_engine,
        ticker_suffix=news_ticker_suffix,
        poll_interval_seconds=settings.fundamentals_poll_interval_seconds,
    )

    macro_service = None
    if macro_indicators:
        macro_service = MacroService(
            indicators=macro_indicators,
            poll_interval_seconds=settings.macro_poll_interval_seconds,
        )

    return MarketContext(
        key=key,
        label=label,
        currency_symbol=currency_symbol,
        universe=universe,
        market_service=market_service,
        scanner_service=scanner_service,
        news_service=news_service,
        autotrader_service=autotrader_service,
        fundamentals_service=fundamentals_service,
        macro_service=macro_service,
        note=note,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info(
        "starting alphascope (env=%s, provider=%s, bist_enabled=%s, paper_trading_only=%s, live_trading_enabled=%s)",
        settings.environment,
        settings.market_data_provider,
        settings.bist_enabled,
        settings.paper_trading_only,
        settings.live_trading_enabled,
    )

    db = Database(settings.database_url)
    db.create_all()
    app.state.db = db

    contexts: dict[str, MarketContext] = {}

    global_universe = Universe(symbols=settings.global_symbol_list, exchange="NASDAQ")
    contexts["global"] = _build_context(
        key="global",
        label="Global (ABD)",
        currency_symbol="$",
        universe=global_universe,
        provider=_build_global_provider(settings, global_universe.symbols),
        settings=settings,
        starting_cash=settings.initial_paper_cash,
        db=db,
        news_ticker_suffix="",
        macro_indicators=[
            ("^GSPC", "S&P 500", "ABD hisse piyasasının genel yönü"),
            ("^VIX", "VIX (Volatilite Endeksi)", "Piyasa risk iştahı — yüksek VIX daha temkinli olun demektir"),
            ("USDTRY=X", "Dolar/TL", "Dolar/TL kuru — genel referans"),
            *_COMMON_MACRO_INDICATORS,
        ],
        note=(
            "Yahoo Finance verisi kullanılıyor; fiyatlar yaklaşık 15-20 dakika "
            "gecikmeli olabilir. Gerçek zamanlı emir kararları için aracı "
            "kurumunuzun kendi verisini mutlaka teyit edin."
        ),
    )

    if settings.bist_enabled:
        bist_universe = Universe(symbols=settings.bist_symbol_list, exchange="BIST")
        contexts["bist"] = _build_context(
            key="bist",
            label="BIST 30",
            currency_symbol="₺",
            universe=bist_universe,
            provider=YFinanceProvider(
                symbols=bist_universe.symbols,
                exchange="BIST",
                poll_interval_seconds=settings.bist_poll_interval_seconds,
            ),
            settings=settings,
            starting_cash=settings.bist_initial_paper_cash,
            db=db,
            news_ticker_suffix=".IS",
            macro_indicators=[
                ("USDTRY=X", "USD/TRY", "Dolar/TL kuru — TL değer kaybı BIST'teki TL bazlı kazancı eritebilir"),
                ("XU100.IS", "BIST 100", "Genel BIST piyasasının yönü"),
                *_COMMON_MACRO_INDICATORS,
            ],
            note=(
                "Yahoo Finance verisi kullanılıyor; fiyatlar yaklaşık 15-20 dakika "
                "gecikmeli olabilir. Gerçek zamanlı emir kararları için aracı "
                "kurumunuzun kendi verisini mutlaka teyit edin."
            ),
        )

    app.state.market_contexts = contexts

    for ctx in contexts.values():
        await ctx.market_service.start()
        await ctx.scanner_service.start()
        if ctx.news_service is not None:
            await ctx.news_service.start()
        if ctx.autotrader_service is not None:
            await ctx.autotrader_service.start()
        if ctx.fundamentals_service is not None:
            await ctx.fundamentals_service.start()
        if ctx.macro_service is not None:
            await ctx.macro_service.start()

    try:
        yield
    finally:
        logger.info("shutting down alphascope")
        for ctx in contexts.values():
            if ctx.macro_service is not None:
                await ctx.macro_service.stop()
            if ctx.fundamentals_service is not None:
                await ctx.fundamentals_service.stop()
            if ctx.autotrader_service is not None:
                await ctx.autotrader_service.stop()
            if ctx.news_service is not None:
                await ctx.news_service.stop()
            await ctx.scanner_service.stop()
            await ctx.market_service.stop()


def _web_dir() -> Path:
    # PyInstaller onefile builds extract bundled data under sys._MEIPASS at runtime.
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    if hasattr(sys, "_MEIPASS"):
        return base / "app" / "web"
    return Path(__file__).resolve().parent / "web"


def create_app() -> FastAPI:
    app = FastAPI(
        title="AlphaScope",
        description=(
            "Gerçek zamanlı piyasa tarayıcı ve karar destek API'si. "
            "Sadece kağıt üzerinde işlem — gerçek emir hiçbir zaman gönderilmez. "
            "Türkçe kontrol paneli için: http://127.0.0.1:8000/"
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.exception_handler(RiskCalculationError)
    async def _risk_error_handler(request: Request, exc: RiskCalculationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.include_router(health.router)
    app.include_router(markets.router)
    app.include_router(market.router)
    app.include_router(scanner.router)
    app.include_router(signals.router)
    app.include_router(news.router)
    app.include_router(fundamentals.router)
    app.include_router(macro.router)
    app.include_router(simulation.router)
    app.include_router(portfolio.router)
    app.include_router(risk.router)

    web_dir = _web_dir()
    if web_dir.is_dir():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")

    return app


app = create_app()
