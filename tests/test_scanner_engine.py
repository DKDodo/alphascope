from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.market_data.models import EventType, MarketEvent
from app.scanner.scanner_engine import ScannerEngine


def _bar(symbol: str, price: float, volume: float, timestamp: datetime) -> MarketEvent:
    return MarketEvent(
        symbol=symbol,
        event_type=EventType.BAR,
        timestamp=timestamp,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=volume,
    )


def test_vwap_uses_only_bars_from_the_most_recent_session():
    engine = ScannerEngine()
    yesterday = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
    today = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)

    # Yesterday's bars sit at price 100 -- if these leaked into VWAP, the
    # result would be pulled well below 200.
    for i in range(5):
        engine.on_event(_bar("AAPL", 100.0, 1000.0, yesterday + timedelta(minutes=i)))
    for i in range(5):
        engine.on_event(_bar("AAPL", 200.0, 1000.0, today + timedelta(minutes=i)))

    indicators = engine.compute_indicators("AAPL")

    assert indicators.vwap == 200.0


def test_vwap_still_volume_weights_within_the_session():
    engine = ScannerEngine()
    today = datetime(2026, 9, 7, 9, 30, tzinfo=timezone.utc)

    engine.on_event(_bar("AAPL", 100.0, 3000.0, today))
    engine.on_event(_bar("AAPL", 200.0, 1000.0, today + timedelta(minutes=1)))

    indicators = engine.compute_indicators("AAPL")

    # (100*3000 + 200*1000) / 4000 = 125
    assert indicators.vwap == 125.0


def test_vwap_none_when_no_bars_yet():
    engine = ScannerEngine()
    assert engine.compute_indicators("AAPL") is None
