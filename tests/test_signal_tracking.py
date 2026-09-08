from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.events import AsyncEventBus
from app.portfolio.paper_portfolio import PaperPortfolio
from app.risk.risk_engine import RiskLevel
from app.scanner.scanner_engine import ScannerEngine
from app.services.scanner_service import ScannerService
from app.signals import tracking_repository
from app.signals.models import CategoryScores, SignalResult, SignalType
from app.signals.signal_engine import SignalEngine
from app.signals.tracking_db_models import TrackedSignal
from app.storage.database import Base, make_engine


@pytest.fixture
def session_factory():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _result(symbol: str, signal: SignalType, price: float, score: int = 80) -> SignalResult:
    return SignalResult(
        symbol=symbol, price=price, score=score, signal=signal,
        reasons=[], risk_level=RiskLevel.MEDIUM,
        category_scores=CategoryScores(trend=0, momentum=0, volume=0, price_action=0, risk_reward=0),
    )


# -- tracking_repository -----------------------------------------------------

def test_record_and_find_due_checkpoint(session_factory):
    old_signal_time = datetime.now(timezone.utc) - timedelta(days=6)
    tracking_repository.record_signal_change(
        session_factory, "global", "AAPL", "STRONG_BUY_SETUP", 90, 100.0, old_signal_time
    )

    due = tracking_repository.find_due_ids(session_factory, "global", 5, datetime.now(timezone.utc))
    assert len(due) == 1


def test_checkpoint_not_yet_due_is_not_returned(session_factory):
    recent_signal_time = datetime.now(timezone.utc) - timedelta(days=1)
    tracking_repository.record_signal_change(
        session_factory, "global", "AAPL", "STRONG_BUY_SETUP", 90, 100.0, recent_signal_time
    )

    due = tracking_repository.find_due_ids(session_factory, "global", 5, datetime.now(timezone.utc))
    assert due == []


def test_filled_checkpoint_no_longer_shows_up_as_due(session_factory):
    old_signal_time = datetime.now(timezone.utc) - timedelta(days=6)
    tracking_repository.record_signal_change(
        session_factory, "global", "AAPL", "STRONG_BUY_SETUP", 90, 100.0, old_signal_time
    )
    row_id = tracking_repository.find_due_ids(session_factory, "global", 5, datetime.now(timezone.utc))[0]

    tracking_repository.fill_checkpoint(session_factory, row_id, 5, 110.0)

    due = tracking_repository.find_due_ids(session_factory, "global", 5, datetime.now(timezone.utc))
    assert due == []


def test_fill_checkpoint_computes_correct_return_pct(session_factory):
    old_signal_time = datetime.now(timezone.utc) - timedelta(days=6)
    tracking_repository.record_signal_change(
        session_factory, "global", "AAPL", "STRONG_BUY_SETUP", 90, 100.0, old_signal_time
    )
    row_id = tracking_repository.find_due_ids(session_factory, "global", 5, datetime.now(timezone.utc))[0]

    tracking_repository.fill_checkpoint(session_factory, row_id, 5, 110.0)

    db = session_factory()
    try:
        row = db.get(TrackedSignal, row_id)
        assert row.price_after_5d == pytest.approx(110.0)
        assert row.return_5d_pct == pytest.approx(10.0)
        assert row.price_after_10d is None  # other horizons untouched
    finally:
        db.close()


def test_performance_summary_averages_and_filters_by_sample_count(session_factory):
    old_signal_time = datetime.now(timezone.utc) - timedelta(days=6)
    # 3 STRONG_BUY_SETUP signals with known 5d returns: +10%, +20%, -6% -> avg 8%
    for entry_price, exit_price in [(100.0, 110.0), (100.0, 120.0), (100.0, 94.0)]:
        tracking_repository.record_signal_change(
            session_factory, "global", "AAPL", "STRONG_BUY_SETUP", 90, entry_price, old_signal_time
        )
    due_ids = tracking_repository.find_due_ids(session_factory, "global", 5, datetime.now(timezone.utc))
    assert len(due_ids) == 3
    for row_id, (_, exit_price) in zip(due_ids, [(100.0, 110.0), (100.0, 120.0), (100.0, 94.0)]):
        tracking_repository.fill_checkpoint(session_factory, row_id, 5, exit_price)

    # a single AVOID signal -- only 1 sample, must be excluded from the summary
    tracking_repository.record_signal_change(
        session_factory, "global", "MSFT", "AVOID", 10, 50.0, old_signal_time
    )
    avoid_id = tracking_repository.find_due_ids(session_factory, "global", 5, datetime.now(timezone.utc))[0]
    tracking_repository.fill_checkpoint(session_factory, avoid_id, 5, 45.0)

    summary = tracking_repository.get_performance_summary(session_factory, "global")

    strong_buy_rows = [s for s in summary if s["signal"] == "STRONG_BUY_SETUP" and s["horizon_days"] == 5]
    assert len(strong_buy_rows) == 1
    assert strong_buy_rows[0]["sample_count"] == 3
    assert strong_buy_rows[0]["avg_return_pct"] == pytest.approx(8.0, abs=0.01)

    avoid_rows = [s for s in summary if s["signal"] == "AVOID"]
    assert avoid_rows == []  # only 1 sample, below the minimum


def test_performance_summary_is_scoped_to_its_market(session_factory):
    old_signal_time = datetime.now(timezone.utc) - timedelta(days=6)
    for _ in range(3):
        tracking_repository.record_signal_change(
            session_factory, "bist", "AKBNK", "BUY_SETUP", 80, 50.0, old_signal_time
        )
    for row_id in tracking_repository.find_due_ids(session_factory, "bist", 5, datetime.now(timezone.utc)):
        tracking_repository.fill_checkpoint(session_factory, row_id, 5, 55.0)

    assert tracking_repository.get_performance_summary(session_factory, "global") == []
    assert len(tracking_repository.get_performance_summary(session_factory, "bist")) == 1


# -- ScannerService integration ----------------------------------------------

def _scanner_service(session_factory) -> ScannerService:
    return ScannerService(
        event_bus=AsyncEventBus(),
        scanner_engine=ScannerEngine(),
        signal_engine=SignalEngine(),
        portfolio=PaperPortfolio(starting_cash=100_000.0),
        market_key="global",
        session_factory=session_factory,
    )


def test_signal_change_creates_a_tracked_row(session_factory):
    service = _scanner_service(session_factory)
    service._track_signal_change("AAPL", _result("AAPL", SignalType.STRONG_BUY_SETUP, 100.0))

    old_now = datetime.now(timezone.utc) + timedelta(days=6)  # pretend enough time passed
    due = tracking_repository.find_due_ids(session_factory, "global", 5, old_now)
    assert len(due) == 1


def test_repeated_identical_signal_does_not_duplicate(session_factory):
    service = _scanner_service(session_factory)
    first = _result("AAPL", SignalType.STRONG_BUY_SETUP, 100.0)
    service._track_signal_change("AAPL", first)
    service._latest_results["AAPL"] = first  # simulate the scan cycle updating _latest_results

    second = _result("AAPL", SignalType.STRONG_BUY_SETUP, 101.0)  # same signal, price ticked
    service._track_signal_change("AAPL", second)

    old_now = datetime.now(timezone.utc) + timedelta(days=6)
    due = tracking_repository.find_due_ids(session_factory, "global", 5, old_now)
    assert len(due) == 1  # not 2 -- the signal didn't actually change


def test_signal_change_to_a_different_type_does_create_a_new_row(session_factory):
    service = _scanner_service(session_factory)
    first = _result("AAPL", SignalType.AVOID, 100.0)
    service._track_signal_change("AAPL", first)
    service._latest_results["AAPL"] = first

    second = _result("AAPL", SignalType.STRONG_BUY_SETUP, 105.0)
    service._track_signal_change("AAPL", second)

    old_now = datetime.now(timezone.utc) + timedelta(days=6)
    due = tracking_repository.find_due_ids(session_factory, "global", 5, old_now)
    assert len(due) == 2
