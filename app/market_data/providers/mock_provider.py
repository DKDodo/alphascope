"""Deterministic-if-seeded synthetic market data provider.

Generates realistic-looking 1-minute OHLCV bars via random walk, with no
external dependency or API key. This is what makes the rest of AlphaScope
runnable out of the box.
"""
from __future__ import annotations

import asyncio
import random
import zlib
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from app.core.logging import get_logger
from app.market_data.base import BaseMarketDataProvider
from app.market_data.models import AssetClass, EventType

logger = get_logger(__name__)

DEFAULT_SYMBOLS: list[str] = [
    "AAPL", "MSFT", "NVDA", "AMD", "META", "TSLA", "AMZN", "GOOGL",
]

_STARTING_PRICES: dict[str, float] = {
    "AAPL": 190.0,
    "MSFT": 420.0,
    "NVDA": 130.0,
    "AMD": 160.0,
    "META": 480.0,
    "TSLA": 250.0,
    "AMZN": 185.0,
    "GOOGL": 175.0,
}


def _stable_seed(seed: int, symbol: str) -> int:
    """crc32, not Python's built-in hash(): str hashing is randomized
    per-process (PYTHONHASHSEED) unless explicitly fixed, which silently
    broke this provider's "deterministic if seeded" claim -- the same
    (seed, symbol) pair produced a different random walk on every restart."""
    return zlib.crc32(f"{seed}:{symbol}".encode())


class _SymbolState:
    __slots__ = ("price", "rng")

    def __init__(self, price: float, rng: random.Random) -> None:
        self.price = price
        self.rng = rng


class MockProvider(BaseMarketDataProvider):
    name = "mock"

    def __init__(
        self,
        symbols: list[str] | None = None,
        tick_interval_seconds: float = 1.0,
        seed: int | None = 42,
    ) -> None:
        super().__init__()
        self._universe = symbols or list(DEFAULT_SYMBOLS)
        self._tick_interval_seconds = tick_interval_seconds
        self._seed = seed
        self._subscribed: set[str] = set()
        self._states: dict[str, _SymbolState] = {}

    async def connect(self) -> None:
        self._connected = True
        logger.info("mock provider connected")

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("mock provider disconnected")

    async def subscribe(self, symbols: list[str]) -> None:
        for symbol in symbols:
            if symbol not in self._states:
                base_seed = None if self._seed is None else _stable_seed(self._seed, symbol)
                start_price = _STARTING_PRICES.get(symbol, 100.0)
                self._states[symbol] = _SymbolState(start_price, random.Random(base_seed))
            self._subscribed.add(symbol)
        logger.info("mock provider subscribed: %s", sorted(self._subscribed))

    async def unsubscribe(self, symbols: list[str]) -> None:
        self._subscribed.difference_update(symbols)
        logger.info("mock provider unsubscribed: %s", symbols)

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        if not self._connected:
            raise RuntimeError("MockProvider.stream() called before connect()")

        while self._connected:
            for symbol in sorted(self._subscribed):
                state = self._states[symbol]
                yield self._next_bar(symbol, state)
            await asyncio.sleep(self._tick_interval_seconds)

    def _next_bar(self, symbol: str, state: _SymbolState) -> dict[str, Any]:
        rng = state.rng
        open_price = state.price

        # Random walk with a small mean-reverting drift so prices don't run away.
        drift = (100.0 - open_price / _STARTING_PRICES.get(symbol, 100.0) * 100.0) * 0.0001
        pct_change = rng.gauss(mu=drift, sigma=0.0015)
        close_price = max(0.01, open_price * (1 + pct_change))

        high_price = max(open_price, close_price) * (1 + abs(rng.gauss(0, 0.0008)))
        low_price = min(open_price, close_price) * (1 - abs(rng.gauss(0, 0.0008)))
        volume = max(1, int(rng.gauss(mu=500_000, sigma=150_000)))

        state.price = close_price

        return {
            "symbol": symbol,
            "asset_class": AssetClass.EQUITY,
            "exchange": "MOCK",
            "timestamp": datetime.now(timezone.utc),
            "event_type": EventType.BAR,
            "open": round(open_price, 4),
            "high": round(high_price, 4),
            "low": round(low_price, 4),
            "close": round(close_price, 4),
            "volume": volume,
        }
