"""Abstract market data provider interface.

Every provider (mock, Massive, and future ones such as BIST/Alpaca/Binance/IBKR)
implements this same interface so the rest of the system never depends on a
specific vendor's API shape.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class BaseMarketDataProvider(ABC):
    name: str = "base"

    def __init__(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @abstractmethod
    async def connect(self) -> None:
        """Establish the provider connection (or prepare a simulated one)."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Tear down the provider connection."""

    @abstractmethod
    async def subscribe(self, symbols: list[str]) -> None:
        """Start receiving events for the given symbols."""

    @abstractmethod
    async def unsubscribe(self, symbols: list[str]) -> None:
        """Stop receiving events for the given symbols."""

    @abstractmethod
    def stream(self) -> AsyncIterator[dict[str, Any]]:
        """Yield raw, provider-native event payloads.

        Consumers must pass each payload through market_data.normalizer
        before using it — never interpret provider-native fields directly.
        """
