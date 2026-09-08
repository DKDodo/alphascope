"""Fetches a single macro indicator (an FX pair or market index) via yfinance.

Uses yf.download() (historical bars) rather than Ticker.info/fast_info:
observed in production that Yahoo's quoteSummary endpoint (which .info
calls) is unreliable from cloud-hosting IPs (Render et al.) — frequently
returns empty data — while the download/chart endpoint yf.download() uses
is not. Since a macro indicator only needs a price and a day-over-day
change, download() covers it without touching the flaky endpoint.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.core.logging import get_logger
from app.macro.models import MacroIndicator

logger = get_logger(__name__)


def _fetch_sync(symbol: str, label: str, description: str) -> MacroIndicator | None:
    import yfinance as yf

    data = yf.download(
        tickers=symbol, period="5d", interval="1d", progress=False, threads=True
    )
    if data.empty:
        return None

    # Recent yfinance versions return MultiIndex columns (Price, Ticker) even
    # for a single ticker, not the flat columns older versions gave.
    close_col = data["Close"]
    if hasattr(close_col, "columns"):
        close_col = close_col.iloc[:, 0]
    closes = close_col.dropna()
    if closes.empty:
        return None

    price = float(closes.iloc[-1])
    change_pct = None
    if len(closes) >= 2:
        prev_close = float(closes.iloc[-2])
        if prev_close:
            change_pct = round((price - prev_close) / prev_close * 100.0, 2)

    return MacroIndicator(
        symbol=symbol, label=label, description=description,
        price=round(price, 4), change_pct=change_pct,
        as_of=datetime.now(timezone.utc),
    )


async def fetch_macro_indicator(symbol: str, label: str, description: str) -> MacroIndicator | None:
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _fetch_sync, symbol, label, description)
    except Exception:  # noqa: BLE001 - a macro data outage must not affect the rest of the app
        logger.exception("failed to fetch macro indicator %s", symbol)
        return None
