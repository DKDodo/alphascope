from __future__ import annotations

import pandas as pd
import pytest

from app.market_data.models import EventType
from app.market_data.normalizer import normalize_event
from app.market_data.providers.yfinance_provider import YFinanceProvider


def _bar_frame(opens, highs, lows, closes, volumes, tz="Europe/Istanbul") -> pd.DataFrame:
    idx = pd.date_range("2026-09-07 10:00:00", periods=len(opens), freq="1min", tz=tz)
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes}, index=idx
    )


def test_parse_download_multi_ticker_returns_latest_bar_per_symbol():
    provider = YFinanceProvider(symbols=["THYAO", "GARAN"])
    thyao = _bar_frame([300, 301], [302, 303], [299, 300.5], [301, 302.5], [1000, 1200])
    garan = _bar_frame([50, 51], [52, 53], [49.5, 50.5], [51, 52.5], [5000, 5500])
    data = pd.concat({"THYAO.IS": thyao, "GARAN.IS": garan}, axis=1)

    events = provider._parse_download(data, ["THYAO", "GARAN"], ["THYAO.IS", "GARAN.IS"])

    assert len(events) == 2
    by_symbol = {e["symbol"]: e for e in events}
    assert by_symbol["THYAO"]["close"] == 302.5
    assert by_symbol["THYAO"]["event_type"] == EventType.BAR
    assert by_symbol["GARAN"]["close"] == 52.5
    assert by_symbol["THYAO"]["exchange"] == "BIST"


def test_parse_download_single_ticker_unwraps_flat_frame():
    provider = YFinanceProvider(symbols=["THYAO"])
    data = _bar_frame([300], [302], [299], [301], [1000])

    events = provider._parse_download(data, ["THYAO"], ["THYAO.IS"])

    assert len(events) == 1
    assert events[0]["symbol"] == "THYAO"
    assert events[0]["close"] == 301


def test_parse_download_single_ticker_is_multiindexed_like_real_yfinance():
    """Verified live: yf.download(tickers=[one_item], group_by="ticker")
    returns MultiIndex columns even for a single-item ticker list -- the
    previous len(tickers) > 1 heuristic got this wrong (treated it as a
    flat frame), so last["Volume"]/last["Open"] etc. raised an uncaught
    KeyError every poll, silently swallowed by stream()'s broad except,
    whenever a market's whole universe was down to one symbol."""
    provider = YFinanceProvider(symbols=["THYAO"])
    thyao = _bar_frame([300], [302], [299], [301], [1000])
    data = pd.concat({"THYAO.IS": thyao}, axis=1)  # real yfinance shape, one symbol

    events = provider._parse_download(data, ["THYAO"], ["THYAO.IS"])

    assert len(events) == 1
    assert events[0]["symbol"] == "THYAO"
    assert events[0]["close"] == 301


def test_parse_download_skips_duplicate_bar_on_repeat_poll():
    provider = YFinanceProvider(symbols=["THYAO"])
    data = _bar_frame([300], [302], [299], [301], [1000])

    first = provider._parse_download(data, ["THYAO"], ["THYAO.IS"])
    second = provider._parse_download(data, ["THYAO"], ["THYAO.IS"])

    assert len(first) == 1
    assert len(second) == 0  # same bar timestamp -> nothing new to emit


def test_parse_download_handles_nan_volume():
    provider = YFinanceProvider(symbols=["THYAO"])
    data = _bar_frame([300], [302], [299], [301], [float("nan")])

    events = provider._parse_download(data, ["THYAO"], ["THYAO.IS"])

    assert events[0]["volume"] == 0.0


def test_parse_download_missing_ticker_is_skipped_not_raised():
    provider = YFinanceProvider(symbols=["THYAO", "MISSING"])
    thyao = _bar_frame([300], [302], [299], [301], [1000])
    data = pd.concat({"THYAO.IS": thyao}, axis=1)

    events = provider._parse_download(data, ["THYAO", "MISSING"], ["THYAO.IS", "MISSING.IS"])

    assert len(events) == 1
    assert events[0]["symbol"] == "THYAO"


def test_yfinance_bar_event_normalizes_like_mock():
    provider = YFinanceProvider(symbols=["THYAO"])
    data = _bar_frame([300], [302], [299], [301], [1000])
    raw = provider._parse_download(data, ["THYAO"], ["THYAO.IS"])[0]

    event = normalize_event("yfinance", raw)

    assert event.symbol == "THYAO"
    assert event.exchange == "BIST"
    assert event.close == 301
    assert event.event_type == EventType.BAR


@pytest.mark.asyncio
async def test_provider_lifecycle_and_subscribe():
    provider = YFinanceProvider(symbols=["THYAO"])
    assert not provider.is_connected
    await provider.connect()
    assert provider.is_connected
    await provider.subscribe(["THYAO", "GARAN"])
    await provider.unsubscribe(["GARAN"])
    assert provider._subscribed == {"THYAO"}
    await provider.disconnect()
    assert not provider.is_connected
