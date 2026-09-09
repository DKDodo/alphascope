"""Fetches daily-bar (EMA50/EMA200) trend direction via yfinance -- a higher
timeframe than the scanner's intraday bars, used by AutoTraderService as a
confirmation gate (see AutoTraderService._process_entries). One batched
yf.download() call for every symbol in a market, mirroring
YFinanceProvider._fetch_latest_bars's batching approach, rather than a
per-symbol request -- daily data changes slowly enough that a single
request per poll cycle is both cheaper and friendlier to Yahoo's rate
limits than N individual calls.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.logging import get_logger
from app.daily_trend.models import DailyTrend
from app.indicators.moving_average import ema

logger = get_logger(__name__)

# ~2 years of daily bars comfortably clears the 200-bar floor EMA200 needs,
# with headroom -- mirrors bars_available's low-data caveat elsewhere.
_LOOKBACK_PERIOD = "2y"


def fetch_daily_trends(symbols: list[str], ticker_suffix: str = "") -> dict[str, DailyTrend]:
    import yfinance as yf  # imported lazily, same as every other yfinance call site

    if not symbols:
        return {}

    tickers = [f"{s}{ticker_suffix}" for s in symbols]
    try:
        data = yf.download(
            tickers=tickers,
            period=_LOOKBACK_PERIOD,
            interval="1d",
            group_by="ticker",
            progress=False,
            threads=True,
        )
    except Exception:  # noqa: BLE001 - a bad Yahoo response must not crash the poll cycle
        logger.exception("daily trend batch download failed")
        return {}

    return _parse_download(data, symbols, tickers)


def _parse_download(data: Any, symbols: list[str], tickers: list[str]) -> dict[str, DailyTrend]:
    import pandas as pd

    # yf.download(group_by="ticker") returns MultiIndex columns even for a
    # single-item ticker list (verified live -- len(tickers) > 1 alone is
    # NOT a reliable signal here) -- see app/backtest/historical_data.py,
    # where this exact heuristic was first found wrong and fixed. The old
    # heuristic left `frame` as the raw MultiIndex frame whenever a
    # market's whole universe was down to one symbol, so frame["Close"]
    # raised KeyError -- caught below, but silently: that symbol got no
    # DailyTrend entry, get_trend() returned None forever, and the
    # daily-trend gate stayed permanently (and invisibly) disabled for it.
    is_multi_indexed = isinstance(data.columns, pd.MultiIndex)

    now = datetime.now(timezone.utc)
    results: dict[str, DailyTrend] = {}
    for symbol, ticker in zip(symbols, tickers):
        try:
            frame = data[ticker] if is_multi_indexed else data
            frame = frame.dropna(how="all")
            closes = frame["Close"].dropna().tolist()
        except (KeyError, IndexError):
            logger.warning("daily trend parse failed for %s -- no trend data this cycle", symbol)
            continue
        if not closes:
            continue

        ema50 = ema(closes, 50)
        ema200 = ema(closes, 200)
        trend_up = ema50 > ema200 if ema50 is not None and ema200 is not None else None
        results[symbol] = DailyTrend(
            symbol=symbol, ema50=ema50, ema200=ema200, trend_up=trend_up, as_of=now
        )
    return results
