"""Minimal async event bus used to decouple market data ingestion from processing.

MarketService publishes normalized MarketEvent objects here; ScannerService
consumes them from a background task. Keeping this indirection (instead of a
direct function call) is what lets ingestion keep running even if a consumer
is temporarily slow, and is the seam future modules (AI analyst, news
sentiment) can also subscribe through.
"""
from __future__ import annotations

import asyncio
from typing import Generic, TypeVar

T = TypeVar("T")


class AsyncEventBus(Generic[T]):
    def __init__(self, maxsize: int = 10_000) -> None:
        self._queue: asyncio.Queue[T] = asyncio.Queue(maxsize=maxsize)

    async def publish(self, item: T) -> None:
        await self._queue.put(item)

    async def get(self) -> T:
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()

    def qsize(self) -> int:
        return self._queue.qsize()
