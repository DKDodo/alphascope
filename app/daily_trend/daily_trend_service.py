"""Periodically fetches and caches each symbol's daily-timeframe trend
direction. Polled far less often than prices -- a daily EMA50/EMA200
relationship doesn't meaningfully change within a single trading day, so
this mirrors FundamentalsService's slow poll cadence rather than the
scanner's minute-scale one.
"""
from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.daily_trend.daily_trend_provider import fetch_daily_trends
from app.daily_trend.models import DailyTrend

logger = get_logger(__name__)


class DailyTrendService:
    def __init__(
        self,
        symbols: list[str],
        ticker_suffix: str = "",
        poll_interval_seconds: float = 21_600.0,  # 6 hours by default
    ) -> None:
        self._symbols = symbols
        self._ticker_suffix = ticker_suffix
        self._poll_interval = poll_interval_seconds

        self._latest: dict[str, DailyTrend] = {}
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        self._stopping = False
        self._task = asyncio.create_task(self._loop(), name="daily-trend-service")

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
            except Exception:  # noqa: BLE001 - a daily-trend cycle failure must not stop the app
                logger.exception("daily trend cycle failed")
            await asyncio.sleep(self._poll_interval)

    async def _run_cycle(self) -> None:
        fetched = await asyncio.to_thread(fetch_daily_trends, self._symbols, self._ticker_suffix)
        if fetched:
            self._latest = fetched
        logger.info("daily trend cycle complete: %d/%d symbols", len(fetched), len(self._symbols))

    def get_trend(self, symbol: str) -> bool | None:
        snapshot = self._latest.get(symbol.upper())
        return snapshot.trend_up if snapshot else None
