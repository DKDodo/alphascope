from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.backtest.models import HistoricalBar
from app.main import _backfill_cold_symbols
from app.scanner.scanner_engine import ScannerEngine


def _bar(close: float, minute: int) -> HistoricalBar:
    return HistoricalBar(
        timestamp=datetime(2026, 9, 8, 9, 30 + minute, tzinfo=timezone.utc),
        open=close, high=close + 0.5, low=close - 0.5, close=close, volume=1000.0,
    )


@pytest.mark.asyncio
async def test_backfill_only_fetches_symbols_with_no_existing_bars(monkeypatch):
    engine = ScannerEngine()
    engine.seed_bar("AAPL", 100, 101, 99, 100.5, 1000, datetime.now(timezone.utc))  # already warm

    captured_symbols: list[str] = []

    def fake_fetch(symbols, ticker_suffix, **kwargs):
        captured_symbols.extend(symbols)
        assert kwargs == {"interval": "1m", "period": "1d"}
        return {"MSFT": [_bar(300, 0), _bar(301, 1), _bar(302, 2)]}

    monkeypatch.setattr("app.main.fetch_historical_series", fake_fetch)

    await _backfill_cold_symbols(engine, "global", ["AAPL", "MSFT"], "")

    assert captured_symbols == ["MSFT"]  # AAPL already had data, so it was skipped
    indicators = engine.compute_indicators("MSFT")
    assert indicators is not None
    assert indicators.bars_available == 3
    assert indicators.price == 302


@pytest.mark.asyncio
async def test_backfill_is_a_noop_when_every_symbol_is_already_warm(monkeypatch):
    engine = ScannerEngine()
    engine.seed_bar("AAPL", 100, 101, 99, 100.5, 1000, datetime.now(timezone.utc))

    def fake_fetch(*args, **kwargs):
        pytest.fail("fetch_historical_series should not be called when no symbol is cold")

    monkeypatch.setattr("app.main.fetch_historical_series", fake_fetch)

    await _backfill_cold_symbols(engine, "global", ["AAPL"], "")


@pytest.mark.asyncio
async def test_backfill_survives_a_fetch_failure(monkeypatch):
    engine = ScannerEngine()

    def fake_fetch(*args, **kwargs):
        raise RuntimeError("yahoo is down")

    monkeypatch.setattr("app.main.fetch_historical_series", fake_fetch)

    await _backfill_cold_symbols(engine, "global", ["AAPL"], "")  # must not raise

    assert not engine.has_data("AAPL")
