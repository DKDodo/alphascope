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

from app.api.routes import health, market, markets, news, portfolio, risk, scanner, signals
from app.config import Settings, get_settings
from app.core.events import AsyncEventBus
from app.core.exceptions import ProviderNotConfiguredError, RiskCalculationError
from app.core.logging import get_logger, setup_logging
from app.market_data.base import BaseMarketDataProvider
from app.market_data.models import MarketEvent
from app.market_data.providers.mock_provider import MockProvider
from app.market_data.providers.yfinance_provider import YFinanceProvider
from app.news.news_service import NewsService
from app.portfolio.paper_portfolio import PaperPortfolio
from app.risk.risk_engine import RiskEngine
from app.scanner.scanner_engine import ScannerEngine
from app.scanner.universe import Universe
from app.services.market_context import MarketContext
from app.services.market_service import MarketService
from app.services.scanner_service import ScannerService
from app.signals.signal_engine import SignalEngine

logger = get_logger(__name__)


def _build_global_provider(settings: Settings) -> BaseMarketDataProvider:
    if settings.market_data_provider == "massive":
        try:
            from app.market_data.providers.massive_provider import MassiveProvider

            return MassiveProvider(api_key=settings.massive_api_key)
        except ProviderNotConfiguredError as exc:
            logger.warning(
                "massive provider not configured (%s); falling back to mock provider", exc
            )
    return MockProvider(
        tick_interval_seconds=settings.mock_tick_interval_seconds,
        seed=settings.mock_random_seed,
    )


def _build_context(
    key: str,
    label: str,
    currency_symbol: str,
    universe: Universe,
    provider: BaseMarketDataProvider,
    settings: Settings,
    starting_cash: float,
    news_ticker_suffix: str = "",
    note: str | None = None,
) -> MarketContext:
    event_bus: AsyncEventBus[MarketEvent] = AsyncEventBus()
    scanner_engine = ScannerEngine()
    signal_engine = SignalEngine(risk_engine=RiskEngine())
    portfolio = PaperPortfolio(starting_cash=starting_cash)

    market_service = MarketService(provider=provider, event_bus=event_bus, symbols=universe.symbols)
    scanner_service = ScannerService(
        event_bus=event_bus,
        scanner_engine=scanner_engine,
        signal_engine=signal_engine,
        portfolio=portfolio,
        scan_interval_seconds=settings.scanner_interval_seconds,
    )

    news_service = None
    if settings.news_enabled:
        news_service = NewsService(
            symbols=universe.symbols,
            ticker_suffix=news_ticker_suffix,
            poll_interval_seconds=settings.news_poll_interval_seconds,
            max_items_per_symbol=settings.news_max_items_per_symbol,
        )

    return MarketContext(
        key=key,
        label=label,
        currency_symbol=currency_symbol,
        universe=universe,
        market_service=market_service,
        scanner_service=scanner_service,
        news_service=news_service,
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

    contexts: dict[str, MarketContext] = {}

    global_universe = Universe(exchange="MOCK")
    contexts["global"] = _build_context(
        key="global",
        label="Global (ABD)",
        currency_symbol="$",
        universe=global_universe,
        provider=_build_global_provider(settings),
        settings=settings,
        starting_cash=settings.initial_paper_cash,
        news_ticker_suffix="",
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
            news_ticker_suffix=".IS",
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

    try:
        yield
    finally:
        logger.info("shutting down alphascope")
        for ctx in contexts.values():
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
    app.include_router(portfolio.router)
    app.include_router(risk.router)

    web_dir = _web_dir()
    if web_dir.is_dir():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")

    return app


app = create_app()
