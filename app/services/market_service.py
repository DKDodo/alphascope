"""Owns the market data provider lifecycle: connect, subscribe, stream, and
reconnect with exponential backoff on failure. A provider error here must
never crash the process or stop the scanner from serving stale-but-valid data.
"""
from __future__ import annotations

import asyncio

from app.core.events import AsyncEventBus
from app.core.exceptions import ProviderConnectionError
from app.core.logging import get_logger
from app.market_data.base import BaseMarketDataProvider
from app.market_data.models import MarketEvent
from app.market_data.normalizer import normalize_event

logger = get_logger(__name__)


class MarketService:
    def __init__(
        self,
        provider: BaseMarketDataProvider,
        event_bus: AsyncEventBus[MarketEvent],
        symbols: list[str],
        max_backoff_seconds: float = 30.0,
    ) -> None:
        self._provider = provider
        self._event_bus = event_bus
        self._symbols = symbols
        self._max_backoff = max_backoff_seconds
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        self._stopping = False
        await self._provider.connect()
        await self._provider.subscribe(self._symbols)
        self._task = asyncio.create_task(self._run_with_reconnect(), name="market-service-ingest")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._provider.disconnect()

    async def _run_with_reconnect(self) -> None:
        backoff = 1.0
        while not self._stopping:
            try:
                async for raw_event in self._provider.stream():
                    backoff = 1.0
                    event = normalize_event(self._provider.name, raw_event)
                    await self._event_bus.publish(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - provider failures must not kill the process
                logger.warning(
                    "market data stream error, reconnecting in %.1fs: %s", backoff, exc
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._max_backoff)
                try:
                    if not self._provider.is_connected:
                        await self._provider.connect()
                        await self._provider.subscribe(self._symbols)
                except ProviderConnectionError as reconnect_exc:
                    logger.warning("reconnect attempt failed: %s", reconnect_exc)
