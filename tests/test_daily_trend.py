from __future__ import annotations

import pandas as pd

from app.daily_trend.daily_trend_provider import _parse_download, fetch_daily_trends


def _daily_frame(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="1D")
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    volumes = [1000.0] * len(closes)
    return pd.DataFrame(
        {"Open": closes, "High": highs, "Low": lows, "Close": closes, "Volume": volumes}, index=idx
    )


def test_parse_download_multi_ticker_detects_trend_direction():
    up_closes = [100.0 + i * 0.5 for i in range(260)]
    down_closes = [200.0 - i * 0.5 for i in range(260)]
    data = pd.concat({"AAPL": _daily_frame(up_closes), "MSFT": _daily_frame(down_closes)}, axis=1)

    results = _parse_download(data, ["AAPL", "MSFT"], ["AAPL", "MSFT"])

    assert results["AAPL"].trend_up is True
    assert results["AAPL"].ema50 > results["AAPL"].ema200
    assert results["MSFT"].trend_up is False
    assert results["MSFT"].ema50 < results["MSFT"].ema200


def test_parse_download_single_ticker_unwraps_flat_frame():
    closes = [100.0 + i * 0.5 for i in range(260)]
    data = _daily_frame(closes)

    results = _parse_download(data, ["AAPL"], ["AAPL"])

    assert "AAPL" in results
    assert results["AAPL"].trend_up is True


def test_parse_download_single_ticker_is_multiindexed_like_real_yfinance():
    """Verified live: yf.download(tickers=[one_item], group_by="ticker")
    returns MultiIndex columns even for a single-item ticker list -- the
    previous len(tickers) > 1 heuristic got this wrong (treated it as a
    flat frame), so frame["Close"] raised KeyError every poll whenever a
    market's whole universe was down to one symbol, silently and
    permanently disabling the daily-trend gate for it."""
    closes = [100.0 + i * 0.5 for i in range(260)]
    data = pd.concat({"AAPL": _daily_frame(closes)}, axis=1)  # real yfinance shape, one symbol

    results = _parse_download(data, ["AAPL"], ["AAPL"])

    assert "AAPL" in results
    assert results["AAPL"].trend_up is True


def test_parse_download_insufficient_history_returns_no_trend():
    closes = [100.0 + i for i in range(30)]  # well under EMA200's 200-bar floor
    data = _daily_frame(closes)

    results = _parse_download(data, ["AAPL"], ["AAPL"])

    assert results["AAPL"].ema200 is None
    assert results["AAPL"].trend_up is None


def test_parse_download_missing_ticker_is_skipped_not_raised():
    closes = [100.0 + i * 0.5 for i in range(260)]
    data = pd.concat({"AAPL": _daily_frame(closes)}, axis=1)

    results = _parse_download(data, ["AAPL", "MISSING"], ["AAPL", "MISSING"])

    assert list(results.keys()) == ["AAPL"]


def test_fetch_daily_trends_empty_symbols_returns_empty_dict():
    assert fetch_daily_trends([]) == {}
