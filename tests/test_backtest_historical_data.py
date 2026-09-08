from __future__ import annotations

import pandas as pd

from app.backtest.historical_data import _parse_download


def _daily_frame(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="1D")
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    opens = [c * 0.995 for c in closes]
    volumes = [1000.0 + i for i in range(len(closes))]
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes}, index=idx
    )


def test_parse_download_single_ticker_is_multiindexed_like_real_yfinance():
    """Verified live: yf.download(tickers=[one_item], group_by="ticker")
    returns MultiIndex columns even for a single-item ticker list -- unlike
    the naive assumption that only len(tickers) > 1 produces a MultiIndex.
    This reproduces that real shape (not a flat frame) for a single symbol."""
    closes = [100.0, 101.0, 99.5, 102.0, 103.0]
    data = pd.concat({"^GSPC": _daily_frame(closes)}, axis=1)

    results = _parse_download(data, ["^GSPC"], ["^GSPC"])

    assert "^GSPC" in results
    bars = results["^GSPC"]
    assert len(bars) == 5
    assert bars[0].close == 100.0
    assert bars[-1].close == 103.0
    assert bars[0].volume == 1000.0


def test_parse_download_multi_ticker_returns_bars_per_symbol():
    closes_a = [100.0, 101.0, 102.0]
    closes_b = [50.0, 49.0, 51.0]
    data = pd.concat({"AAPL": _daily_frame(closes_a), "MSFT": _daily_frame(closes_b)}, axis=1)

    results = _parse_download(data, ["AAPL", "MSFT"], ["AAPL", "MSFT"])

    assert set(results.keys()) == {"AAPL", "MSFT"}
    assert [b.close for b in results["AAPL"]] == closes_a
    assert [b.close for b in results["MSFT"]] == closes_b


def test_parse_download_skips_rows_with_missing_ohlc():
    closes = [100.0, float("nan"), 102.0]
    data = pd.concat({"AAPL": _daily_frame(closes)}, axis=1)

    results = _parse_download(data, ["AAPL"], ["AAPL"])

    assert len(results["AAPL"]) == 2  # the NaN row is dropped, not crashed on


def test_parse_download_missing_ticker_is_skipped_not_raised():
    closes = [100.0, 101.0]
    data = pd.concat({"AAPL": _daily_frame(closes)}, axis=1)

    results = _parse_download(data, ["AAPL", "MISSING"], ["AAPL", "MISSING"])

    assert list(results.keys()) == ["AAPL"]
