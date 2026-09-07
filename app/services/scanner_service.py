"""Consumes normalized market events, maintains scanner state, and runs the
periodic scan cycle that produces cached SignalResults for the API."""
from __future__ import annotations

import asyncio

from app.core.events import AsyncEventBus
from app.core.logging import get_logger
from app.market_data.models import MarketEvent
from app.portfolio.paper_portfolio import PaperPortfolio
from app.scanner.scanner_engine import ScannerEngine
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
    ) -> None:
        self._event_bus = event_bus
        self._scanner_engine = scanner_engine
        self._signal_engine = signal_engine
        self._portfolio = portfolio
        self._scan_interval = scan_interval_seconds

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
            except Exception:  # noqa: BLE001 - one bad event must not stop ingestion
                logger.exception("failed to process market event for %s", event.symbol)
            finally:
                self._event_bus.task_done()

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
            result = self._signal_engine.evaluate(indicators)
            if result is not None:
                results[symbol] = result
        if results:
            self._latest_results = results
            logger.info("scan cycle complete: %d symbols evaluated", len(results))

    def get_scan_results(self) -> list[SignalResult]:
        return list(self._latest_results.values())

    def get_signal(self, symbol: str) -> SignalResult | None:
        return self._latest_results.get(symbol.upper())

    @property
    def portfolio(self) -> PaperPortfolio:
        return self._portfolio
