"""Real (delayed) BIST market data via Yahoo Finance (yfinance).

Yahoo Finance data for Borsa İstanbul symbols is typically delayed roughly
15-20 minutes and is not a broker-grade real-time feed — see README.md. This
provider polls `yfinance.download()` on an interval instead of streaming,
since Yahoo has no push/WebSocket API; polling faster than the data actually
updates would just re-read the same stale bar while risking rate limiting.

Implements the same BaseMarketDataProvider interface as every other
provider, so the scanner/signal/risk pipeline is completely unaware this
isn't a push feed.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timezone
from typing import Any

from app.core.logging import get_logger
from app.market_data.base import BaseMarketDataProvider
from app.market_data.models import AssetClass, EventType

logger = get_logger(__name__)


class YFinanceProvider(BaseMarketDataProvider):
    name = "yfinance"

    def __init__(
        self,
        symbols: list[str],
        exchange: str = "BIST",
        poll_interval_seconds: float = 60.0,
        ticker_suffix: str = ".IS",
    ) -> None:
        super().__init__()
        self._exchange = exchange
        self._poll_interval = poll_interval_seconds
        self._suffix = ticker_suffix
        self._subscribed: set[str] = set()
        self._last_bar_time: dict[str, Any] = {}
        self._universe_hint = symbols

    async def connect(self) -> None:
        self._connected = True
        logger.info("yfinance provider connected (exchange=%s)", self._exchange)

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("yfinance provider disconnected")

    async def subscribe(self, symbols: list[str]) -> None:
        self._subscribed.update(symbols)
        logger.info("yfinance provider subscribed: %s", sorted(self._subscribed))

    async def unsubscribe(self, symbols: list[str]) -> None:
        self._subscribed.difference_update(symbols)

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        if not self._connected:
            raise RuntimeError("YFinanceProvider.stream() called before connect()")

        loop = asyncio.get_running_loop()
        while self._connected:
            symbols = sorted(self._subscribed)
            bars: list[dict[str, Any]] = []
            if symbols:
                try:
                    bars = await loop.run_in_executor(None, self._fetch_latest_bars, symbols)
                except Exception:  # noqa: BLE001 - a bad Yahoo response must not kill the scanner
                    logger.exception("yfinance fetch failed")
            for bar in bars:
                yield bar
            await asyncio.sleep(self._poll_interval)

    def _fetch_latest_bars(self, symbols: list[str]) -> list[dict[str, Any]]:
        import yfinance as yf  # imported lazily: BIST-less setups never pay this import cost

        tickers = [f"{s}{self._suffix}" for s in symbols]
        data = yf.download(
            tickers=tickers,
            period="1d",
            interval="1m",
            group_by="ticker",
            progress=False,
            threads=True,
        )
        return self._parse_download(data, symbols, tickers)

    def _parse_download(self, data: Any, symbols: list[str], tickers: list[str]) -> list[dict[str, Any]]:
        import pandas as pd

        results: list[dict[str, Any]] = []
        for symbol, ticker in zip(symbols, tickers):
            try:
                frame = data[ticker] if len(tickers) > 1 else data
                frame = frame.dropna(how="all")
                if frame.empty:
                    continue
                last = frame.iloc[-1]
                bar_time = frame.index[-1].to_pydatetime()
            except (KeyError, IndexError):
                continue

            if self._last_bar_time.get(symbol) == bar_time:
                continue  # no new bar published since the last poll
            self._last_bar_time[symbol] = bar_time

            if bar_time.tzinfo is None:
                bar_time = bar_time.replace(tzinfo=timezone.utc)

            volume = last["Volume"]
            results.append(
                {
                    "symbol": symbol,
                    "asset_class": AssetClass.EQUITY,
                    "exchange": self._exchange,
                    "timestamp": bar_time,
                    "event_type": EventType.BAR,
                    "open": float(last["Open"]),
                    "high": float(last["High"]),
                    "low": float(last["Low"]),
                    "close": float(last["Close"]),
                    "volume": 0.0 if pd.isna(volume) else float(volume),
                }
            )
        return results
