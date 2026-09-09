"""Historical OHLCV data via yfinance -- the same batched-download +
ticker-shape parsing pattern as app/daily_trend/daily_trend_provider.py, but
returns full OHLCV bars (not just closes) since callers need everything
ScannerEngine.seed_bar() takes. Symbols yfinance can't resolve are simply
absent from the result -- never raises, matching the rest of this
codebase's yfinance call sites.

Two callers: the backtest engine (years of daily bars) and app/main.py's
live-scanner cold-start backfill (a single day of 1-minute bars, via the
`interval`/`period` override) -- see _backfill_cold_symbols in app/main.py.
"""
from __future__ import annotations

from datetime import timezone
from typing import Any

from app.backtest.models import HistoricalBar
from app.core.logging import get_logger

logger = get_logger(__name__)


def fetch_historical_series(
    symbols: list[str],
    ticker_suffix: str = "",
    years: int = 3,
    interval: str = "1d",
    period: str | None = None,
) -> dict[str, list[HistoricalBar]]:
    """Batched bar fetch for every symbol in `symbols`, oldest-first.
    Defaults to `years` years of daily bars; pass `interval`/`period`
    directly (e.g. interval="1m", period="1d") to fetch intraday bars
    instead -- `period` always wins over `years` when both are given."""
    import yfinance as yf

    if not symbols:
        return {}

    tickers = [f"{s}{ticker_suffix}" for s in symbols]
    try:
        data = yf.download(
            tickers=tickers,
            period=period or f"{max(1, years)}y",
            interval=interval,
            group_by="ticker",
            progress=False,
            threads=True,
        )
    except Exception:  # noqa: BLE001 - a bad Yahoo response must not crash the caller
        logger.exception("historical batch download failed")
        return {}

    return _parse_download(data, symbols, tickers)


def fetch_single_series(symbol: str, years: int = 3) -> list[HistoricalBar]:
    """Convenience wrapper for a single symbol (a benchmark index, ^VIX)."""
    result = fetch_historical_series([symbol], "", years)
    return result.get(symbol, [])


def _parse_download(data: Any, symbols: list[str], tickers: list[str]) -> dict[str, list[HistoricalBar]]:
    import pandas as pd

    results: dict[str, list[HistoricalBar]] = {}
    # yf.download(group_by="ticker") returns MultiIndex columns even for a
    # single-item ticker list (verified live -- len(tickers) > 1 alone is
    # NOT a reliable signal here, unlike what it might look like at a glance).
    is_multi_indexed = isinstance(data.columns, pd.MultiIndex)
    for symbol, ticker in zip(symbols, tickers):
        try:
            frame = data[ticker] if is_multi_indexed else data
            frame = frame.dropna(how="all")
        except (KeyError, IndexError):
            continue
        if frame.empty:
            continue

        bars: list[HistoricalBar] = []
        for index, row in frame.iterrows():
            if pd.isna(row["Open"]) or pd.isna(row["High"]) or pd.isna(row["Low"]) or pd.isna(row["Close"]):
                continue
            timestamp = index.to_pydatetime()
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            volume = row.get("Volume")
            bars.append(HistoricalBar(
                timestamp=timestamp,
                open=float(row["Open"]), high=float(row["High"]),
                low=float(row["Low"]), close=float(row["Close"]),
                volume=0.0 if pd.isna(volume) else float(volume),
            ))
        if bars:
            results[symbol] = bars
    return results
