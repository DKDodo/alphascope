"""Real-time crypto market data via Binance's public combined-stream
WebSocket. No API key or account needed -- unlike MassiveProvider, there is
no "not configured" failure mode here.

Optional, opt-in replacement for YFinanceProvider on the crypto tab only
(see CRYPTO_MARKET_DATA_PROVIDER in app/config.py). Global and BIST are
untouched.

Subscribes via a JSON SUBSCRIBE message over a single bare-stream
connection (`wss://.../stream` with no symbols in the URL), not the
alternative URL-embedded form (`?streams=a@kline_1m,b@kline_1m`) -- verified
live that the URL form gets rejected (HTTP 400) as soon as it contains more
than one stream (likely how an intermediary on this network handles `@` +
`,` in a query string), while the SUBSCRIBE-message form works for any
number of symbols and matches MassiveProvider's own connect-then-subscribe
sequencing.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from app.core.exceptions import ProviderConnectionError
from app.core.logging import get_logger
from app.market_data.base import BaseMarketDataProvider
from app.market_data.models import AssetClass, EventType

logger = get_logger(__name__)

try:
    import websockets
except ImportError:  # pragma: no cover - websockets is a required dependency, guarded defensively
    websockets = None  # type: ignore[assignment]

BINANCE_WS_URL = "wss://stream.binance.com:9443/stream"


class BinanceProvider(BaseMarketDataProvider):
    name = "binance"

    def __init__(
        self,
        symbols: list[str],
        quote_asset: str = "USDT",
        exchange: str = "CRYPTO",
        kline_interval: str = "1m",
        max_reconnect_backoff_seconds: float = 30.0,
    ) -> None:
        super().__init__()
        self._quote_asset = quote_asset.strip().upper()
        self._exchange = exchange
        self._kline_interval = kline_interval
        self._max_backoff = max_reconnect_backoff_seconds
        self._subscribed: set[str] = set()
        self._pair_to_symbol: dict[str, str] = {}
        self._universe_hint = symbols
        self._ws: Any = None
        self._next_id = 1

    async def connect(self) -> None:
        if websockets is None:
            raise ProviderConnectionError("The 'websockets' package is not installed.")
        try:
            # Default open_timeout (10s) was observed to be too tight for a
            # cold DNS/TLS handshake on some networks, aborting the very
            # first connection attempt even though the endpoint is reachable
            # (verified live -- the same connect succeeds well within 20s on
            # a warm lookup). MarketService's own reconnect-with-backoff loop
            # still covers a genuinely unreachable endpoint.
            self._ws = await websockets.connect(BINANCE_WS_URL, open_timeout=20)
            self._connected = True
            logger.info("binance provider connected")
        except Exception as exc:  # noqa: BLE001 - surfaced as a typed provider error
            raise ProviderConnectionError(f"Failed to connect to Binance: {exc}") from exc

    async def disconnect(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        self._connected = False
        logger.info("binance provider disconnected")

    async def subscribe(self, symbols: list[str]) -> None:
        self._subscribed.update(symbols)
        for s in symbols:
            self._pair_to_symbol[self.to_binance_pair(s, self._quote_asset)] = s.upper()
        if self._ws is not None:
            await self._send_subscription("SUBSCRIBE", self._subscribed)
        logger.info("binance provider subscribed: %s", sorted(self._subscribed))

    async def unsubscribe(self, symbols: list[str]) -> None:
        self._subscribed.difference_update(symbols)
        if self._ws is not None:
            await self._send_subscription("UNSUBSCRIBE", symbols)
        logger.info("binance provider unsubscribed: %s", symbols)

    async def _send_subscription(self, method: str, symbols: set[str] | list[str]) -> None:
        streams = [
            f"{self.to_binance_pair(s, self._quote_asset).lower()}@kline_{self._kline_interval}"
            for s in symbols
        ]
        if not streams:
            return
        await self._ws.send(json.dumps({"method": method, "params": streams, "id": self._next_id}))
        self._next_id += 1

    @staticmethod
    def to_binance_pair(symbol: str, quote_asset: str) -> str:
        """'btc', 'USDT' -> 'BTCUSDT' (Binance's concatenated pair format)."""
        return f"{symbol.strip().upper()}{quote_asset.strip().upper()}"

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        if not self._connected:
            raise RuntimeError("BinanceProvider.stream() called before connect()")

        backoff = 1.0
        while self._connected:
            try:
                assert self._ws is not None
                async for raw_message in self._ws:
                    backoff = 1.0
                    try:
                        message = json.loads(raw_message)
                    except (json.JSONDecodeError, TypeError):
                        logger.warning("binance: dropped a non-JSON message")
                        continue
                    parsed = self._parse_kline_message(message, self._pair_to_symbol, self._exchange)
                    if parsed is not None:
                        yield parsed
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a dropped connection (incl. Binance's normal 24h force-close) must never kill the scanner
                logger.warning("binance stream error, reconnecting in %.1fs: %s", backoff, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._max_backoff)
                try:
                    await self.connect()
                    if self._subscribed:
                        await self._send_subscription("SUBSCRIBE", self._subscribed)
                except ProviderConnectionError:
                    continue

    @staticmethod
    def _parse_kline_message(
        message: dict[str, Any], pair_to_symbol: dict[str, str], exchange: str
    ) -> dict[str, Any] | None:
        """Pure function: one already-json.loads'd message -> normalized-shape
        raw dict, or None (a SUBSCRIBE ack, a still-forming kline, an
        unrecognized pair, or a malformed payload). Never raises."""
        if not isinstance(message, dict):
            return None
        data = message.get("data")
        if not isinstance(data, dict):
            return None  # e.g. a {"result": null, "id": 1} SUBSCRIBE ack
        kline = data.get("k")
        if not isinstance(kline, dict):
            return None
        if not kline.get("x"):
            return None  # still forming -- must be dropped, not treated as a new bar

        pair = kline.get("s")
        symbol = pair_to_symbol.get(pair) if isinstance(pair, str) else None
        if symbol is None:
            return None  # unrecognized/unsubscribed pair -- defensive, shouldn't normally happen

        try:
            return {
                "symbol": symbol,
                "asset_class": AssetClass.CRYPTO,
                "exchange": exchange,
                "timestamp": datetime.fromtimestamp(kline["T"] / 1000, tz=timezone.utc),
                "event_type": EventType.BAR,
                "open": float(kline["o"]),
                "high": float(kline["h"]),
                "low": float(kline["l"]),
                "close": float(kline["c"]),
                "volume": float(kline["v"]),
            }
        except (KeyError, TypeError, ValueError):
            return None
