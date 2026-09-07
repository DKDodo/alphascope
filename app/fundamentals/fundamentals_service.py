"""Periodically fetches and caches fundamental data for every symbol in a
market's universe. Polled far less often than prices/news — company
fundamentals (P/E, margins, growth) move on a quarterly-earnings timescale,
not a minute-to-minute one."""
from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.fundamentals.fundamentals_provider import fetch_fundamental_snapshot
from app.fundamentals.long_term_scoring import evaluate_long_term_outlook
from app.fundamentals.models import FundamentalSnapshot, LongTermOutlook
from app.scanner.scanner_engine import ScannerEngine

logger = get_logger(__name__)


class FundamentalsService:
    def __init__(
        self,
        symbols: list[str],
        scanner_engine: ScannerEngine,
        ticker_suffix: str = "",
        poll_interval_seconds: float = 21_600.0,  # 6 hours by default
    ) -> None:
        self._symbols = symbols
        self._scanner_engine = scanner_engine
        self._ticker_suffix = ticker_suffix
        self._poll_interval = poll_interval_seconds

        self._latest: dict[str, FundamentalSnapshot] = {}
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        self._stopping = False
        self._task = asyncio.create_task(self._loop(), name="fundamentals-service")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self._run_cycle()
            except Exception:  # noqa: BLE001 - a fundamentals cycle failure must not stop the app
                logger.exception("fundamentals cycle failed")
            await asyncio.sleep(self._poll_interval)

    async def _run_cycle(self) -> None:
        snapshots = await asyncio.gather(
            *[fetch_fundamental_snapshot(symbol, self._ticker_suffix) for symbol in self._symbols]
        )
        found = 0
        for symbol, snapshot in zip(self._symbols, snapshots):
            if snapshot is not None:
                self._latest[symbol] = snapshot
                found += 1
        logger.info("fundamentals cycle complete: %d/%d symbols", found, len(self._symbols))

    def get_long_term_outlook(self, symbol: str) -> LongTermOutlook:
        symbol = symbol.upper()
        snapshot = self._latest.get(symbol)
        trend_up = self._long_term_trend_up(symbol)
        return evaluate_long_term_outlook(snapshot, trend_up)

    def _long_term_trend_up(self, symbol: str) -> bool | None:
        indicators = self._scanner_engine.compute_indicators(symbol)
        if indicators is None or indicators.ema50 is None or indicators.ema200 is None:
            return None
        return indicators.ema50 > indicators.ema200
