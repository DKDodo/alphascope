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


def test_out_of_order_live_bar_is_dropped():
    engine = ScannerEngine()
    later = datetime(2026, 9, 7, 12, 5, tzinfo=timezone.utc)
    earlier = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)

    engine.on_event(_bar("AAPL", 200.0, 1000.0, later))
    engine.on_event(_bar("AAPL", 100.0, 1000.0, earlier))  # arrives out of order

    indicators = engine.compute_indicators("AAPL")

    assert indicators.price == 200.0  # the earlier bar must not have overwritten it
    assert indicators.bars_available == 1


def test_equal_timestamp_bar_is_still_accepted():
    # Not a race case -- a legitimate repeat poll (or a revised print for
    # the same bar) must still go through, only strictly-older bars are dropped.
    engine = ScannerEngine()
    ts = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)

    engine.on_event(_bar("AAPL", 100.0, 1000.0, ts))
    engine.on_event(_bar("AAPL", 101.0, 1000.0, ts))

    indicators = engine.compute_indicators("AAPL")

    assert indicators.price == 101.0
    assert indicators.bars_available == 2


def test_seed_bar_older_than_an_already_arrived_live_bar_is_dropped():
    """The exact scenario the audit found: main.py's cold-start backfill
    task (seed_bar, historical) can race the live provider's own stream()
    task (on_event) -- if a live bar wins, seed_bar()'s older historical
    bars must not be appended after it, or closes[-1] ("current price"
    everywhere) would become a stale historical close."""
    engine = ScannerEngine()
    live_time = datetime(2026, 9, 7, 12, 5, tzinfo=timezone.utc)
    historical_time = datetime(2026, 9, 7, 11, 0, tzinfo=timezone.utc)

    engine.on_event(_bar("AAPL", 200.0, 1000.0, live_time))  # live bar wins the race
    engine.seed_bar("AAPL", 100.0, 100.0, 100.0, 100.0, 1000.0, historical_time)  # backfill arrives late

    indicators = engine.compute_indicators("AAPL")

    assert indicators.price == 200.0
    assert indicators.bars_available == 1


def test_seed_bar_in_chronological_order_still_works():
    # Normal DB warm-start / backfill path (no race): historical bars
    # arriving in order, before any live bar, must be entirely unaffected.
    engine = ScannerEngine()
    t0 = datetime(2026, 9, 7, 9, 30, tzinfo=timezone.utc)

    for i in range(5):
        engine.seed_bar("AAPL", 100.0 + i, 100.0 + i, 100.0 + i, 100.0 + i, 1000.0, t0 + timedelta(minutes=i))

    indicators = engine.compute_indicators("AAPL")

    assert indicators.price == 104.0
    assert indicators.bars_available == 5
