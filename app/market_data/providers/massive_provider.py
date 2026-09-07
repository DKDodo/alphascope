"""Skeleton WebSocket provider for the Massive market data feed.

Intentionally inert unless a real API key is configured: it never attempts a
connection without one, so `MARKET_DATA_PROVIDER=massive` without a key fails
fast and loud instead of silently hanging.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from app.core.exceptions import ProviderConnectionError, ProviderNotConfiguredError
from app.core.logging import get_logger

logger = get_logger(__name__)

try:
    import websockets
except ImportError:  # pragma: no cover - websockets is a required dependency, guarded defensively
    websockets = None  # type: ignore[assignment]

from app.market_data.base import BaseMarketDataProvider

MASSIVE_WS_URL = "wss://api.massive.example/v1/stream"  # placeholder — replace with real endpoint


class MassiveProvider(BaseMarketDataProvider):
    name = "massive"

    def __init__(self, api_key: str | None, max_reconnect_backoff_seconds: float = 30.0) -> None:
        super().__init__()
        if not api_key:
            raise ProviderNotConfiguredError(
                "MassiveProvider requires MASSIVE_API_KEY to be set; refusing to connect without it."
            )
        self._api_key = api_key
        self._max_backoff = max_reconnect_backoff_seconds
        self._subscribed: set[str] = set()
        self._ws: Any = None

    async def connect(self) -> None:
        if websockets is None:
            raise ProviderConnectionError("The 'websockets' package is not installed.")
        try:
            self._ws = await websockets.connect(MASSIVE_WS_URL)
            self._connected = True
            logger.info("massive provider connected")
        except Exception as exc:  # noqa: BLE001 - surfaced as a typed provider error
            raise ProviderConnectionError(f"Failed to connect to Massive: {exc}") from exc

    async def disconnect(self) -> None:
        if self._ws is not None:
            await self._ws.close()
        self._connected = False
        logger.info("massive provider disconnected")

    async def subscribe(self, symbols: list[str]) -> None:
        self._subscribed.update(symbols)
        if self._ws is not None:
            await self._ws.send(json.dumps({"action": "subscribe", "symbols": symbols}))
        logger.info("massive provider subscribed: %s", sorted(self._subscribed))

    async def unsubscribe(self, symbols: list[str]) -> None:
        self._subscribed.difference_update(symbols)
        if self._ws is not None:
            await self._ws.send(json.dumps({"action": "unsubscribe", "symbols": symbols}))
        logger.info("massive provider unsubscribed: %s", symbols)

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        """Yield raw Massive payloads, reconnecting with exponential backoff on failure.

        A failure here must never propagate out and kill the scanner — the
        caller (MarketService) also wraps this in its own retry loop, but the
        backoff lives here too since reconnect strategy is provider-specific.
        """
        backoff = 1.0
        while self._connected:
            try:
                assert self._ws is not None
                async for raw_message in self._ws:
                    backoff = 1.0
                    yield json.loads(raw_message)
            except Exception as exc:  # noqa: BLE001
                logger.warning("massive stream error, reconnecting in %.1fs: %s", backoff, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._max_backoff)
                try:
                    await self.connect()
                    if self._subscribed:
                        await self.subscribe(sorted(self._subscribed))
                except ProviderConnectionError:
                    continue
