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
from zoneinfo import ZoneInfo

from app.core.logging import get_logger
from app.macro.models import MacroIndicator

logger = get_logger(__name__)

_ISTANBUL = ZoneInfo("Europe/Istanbul")


def _extract_closes(data):
    # Recent yfinance versions return MultiIndex columns (Price, Ticker) even
    # for a single ticker, not the flat columns older versions gave.
    close_col = data["Close"]
    if hasattr(close_col, "columns"):
        close_col = close_col.iloc[:, 0]
    return close_col.dropna()


def _fetch_previous_close_change(symbol: str) -> tuple[float, float | None] | None:
    """Change % vs. the previous daily close — the conventional definition
    exchange-hours instruments use (stocks, indices, FX, futures): there's
    already a natural "day" boundary at the session close."""
    import yfinance as yf

    data = yf.download(tickers=symbol, period="5d", interval="1d", progress=False, threads=True)
    if data.empty:
        return None
    closes = _extract_closes(data)
    if closes.empty:
        return None

    price = float(closes.iloc[-1])
    change_pct = None
    if len(closes) >= 2:
        prev_close = float(closes.iloc[-2])
        if prev_close:
            change_pct = round((price - prev_close) / prev_close * 100.0, 2)
    return price, change_pct


def _fetch_day_start_change(symbol: str) -> tuple[float, float | None] | None:
    """Change % vs. the first bar at/after today's 00:00 Turkey time.
    Meaningful for a 24/7 asset like crypto, which has no exchange session
    and thus no natural "previous close" — mirrors how most mobile trading
    apps show a fixed local-day change for these. Uses hourly bars, since
    that's granular enough to find the day boundary without hitting
    Yahoo's tighter history limits on minute-level data."""
    import yfinance as yf

    data = yf.download(tickers=symbol, period="2d", interval="1h", progress=False, threads=True)
    if data.empty:
        return None
    closes = _extract_closes(data)
    if closes.empty:
        return None

    index = closes.index
    if index.tz is None:
        index = index.tz_localize("UTC")
    local_index = index.tz_convert(_ISTANBUL)

    price = float(closes.iloc[-1])
    today_start = datetime.now(_ISTANBUL).replace(hour=0, minute=0, second=0, microsecond=0)
    mask = local_index >= today_start
    day_open_price = float(closes[mask].iloc[0]) if mask.any() else float(closes.iloc[0])

    change_pct = round((price - day_open_price) / day_open_price * 100.0, 2) if day_open_price else None
    return price, change_pct


def _fetch_sync(
    symbol: str, label: str, description: str, day_reset: bool = False
) -> MacroIndicator | None:
    result = (
        _fetch_day_start_change(symbol) if day_reset else _fetch_previous_close_change(symbol)
    )
    if result is None:
        return None
    price, change_pct = result

    return MacroIndicator(
        symbol=symbol, label=label, description=description,
        price=round(price, 4), change_pct=change_pct,
        as_of=datetime.now(timezone.utc),
    )


async def fetch_macro_indicator(
    symbol: str, label: str, description: str, day_reset: bool = False
) -> MacroIndicator | None:
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _fetch_sync, symbol, label, description, day_reset)
    except Exception:  # noqa: BLE001 - a macro data outage must not affect the rest of the app
        logger.exception("failed to fetch macro indicator %s", symbol)
        return None
