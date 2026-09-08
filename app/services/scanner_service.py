"""Consumes normalized market events, maintains scanner state, and runs the
periodic scan cycle that produces cached SignalResults for the API."""
from __future__ import annotations

import asyncio

from sqlalchemy.orm import Session, sessionmaker

from app.core.events import AsyncEventBus
from app.core.logging import get_logger
from app.daily_trend.daily_trend_service import DailyTrendService
from app.market_data.models import EventType, MarketEvent
from app.portfolio.paper_portfolio import PaperPortfolio
from app.scanner import bar_repository
from app.scanner.scanner_engine import ScannerEngine
from app.signals import tracking_repository
from app.signals.models import SignalResult
from app.signals.signal_engine import SignalEngine

logger = get_logger(__name__)


class ScannerService:
    def __init__(
        self,
        event_bus: AsyncEventBus[MarketEvent],
        scanner_engine: ScannerEngine,
        signal_engine: SignalEngine,
        portfolio: PaperPortfolio,
        scan_interval_seconds: float = 5.0,
        market_key: str | None = None,
        session_factory: sessionmaker[Session] | None = None,
        daily_trend_service: DailyTrendService | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._scanner_engine = scanner_engine
        self._signal_engine = signal_engine
        self._portfolio = portfolio
        self._scan_interval = scan_interval_seconds
        # Persists each new bar so the rolling indicator window survives a
        # restart (see bar_repository.py / ScannerEngine.seed_bar). Optional:
        # tests can construct a ScannerService without a database at all.
        self._market_key = market_key
        self._session_factory = session_factory
        self._daily_trend_service = daily_trend_service

        self._latest_results: dict[str, SignalResult] = {}
        self._consumer_task: asyncio.Task | None = None
        self._scan_task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        self._stopping = False
        self._consumer_task = asyncio.create_task(self._consume_events(), name="scanner-consume")
        self._scan_task = asyncio.create_task(self._scan_loop(), name="scanner-cycle")

    async def stop(self) -> None:
        self._stopping = True
        for task in (self._consumer_task, self._scan_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def _consume_events(self) -> None:
        while not self._stopping:
            event = await self._event_bus.get()
            try:
                self._scanner_engine.on_event(event)
                if event.price is not None:
                    self._portfolio.update_market_price(event.symbol, event.price)
                await self._persist_bar(event)
            except Exception:  # noqa: BLE001 - one bad event must not stop ingestion
                logger.exception("failed to process market event for %s", event.symbol)
            finally:
                self._event_bus.task_done()

    async def _persist_bar(self, event: MarketEvent) -> None:
        if self._session_factory is None or self._market_key is None:
            return
        if event.event_type is not EventType.BAR:
            return
        if event.open is None or event.high is None or event.low is None or event.close is None:
            return
        await asyncio.to_thread(
            bar_repository.save_bar,
            self._session_factory,
            self._market_key,
            event.symbol,
            event.timestamp,
            event.open,
            event.high,
            event.low,
            event.close,
            event.volume or 0.0,
        )

    async def _scan_loop(self) -> None:
        while not self._stopping:
            try:
                self._run_scan_cycle()
            except Exception:  # noqa: BLE001 - a scan cycle failure must not stop the scanner
                logger.exception("scan cycle failed")
            await asyncio.sleep(self._scan_interval)

    def _run_scan_cycle(self) -> None:
        symbols = self._scanner_engine.tracked_symbols()
        results: dict[str, SignalResult] = {}
        for symbol in symbols:
            indicators = self._scanner_engine.compute_indicators(symbol)
            if indicators is None:
                continue
            daily_trend_up = (
                self._daily_trend_service.get_trend(symbol) if self._daily_trend_service else None
            )
            result = self._signal_engine.evaluate(indicators, daily_trend_up=daily_trend_up)
            if result is not None:
                self._track_signal_change(symbol, result)
                results[symbol] = result
        if results:
            self._latest_results = results
            logger.info("scan cycle complete: %d symbols evaluated", len(results))

    def _track_signal_change(self, symbol: str, result: SignalResult) -> None:
        """Records a new tracked-signal row the moment a symbol's signal
        actually changes (not every scan cycle, which would flood the table
        with duplicates of a signal that's held steady for hours) -- see
        app/signals/signal_tracking_service.py for how these rows later get
        their N-days-later outcome filled in."""
        if self._session_factory is None or self._market_key is None:
            return
        previous = self._latest_results.get(symbol)
        if previous is not None and previous.signal == result.signal:
            return
        tracking_repository.record_signal_change(
            self._session_factory,
            self._market_key,
            symbol,
            result.signal.value,
            result.score,
            result.price,
            result.timestamp,
        )

    def get_scan_results(self) -> list[SignalResult]:
        return list(self._latest_results.values())

    def get_signal(self, symbol: str) -> SignalResult | None:
        return self._latest_results.get(symbol.upper())

    @property
    def portfolio(self) -> PaperPortfolio:
        return self._portfolio
