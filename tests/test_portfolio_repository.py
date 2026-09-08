from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from app.portfolio import portfolio_repository
from app.portfolio.models import Position
from app.storage.database import Base, make_engine


@pytest.fixture
def session_factory():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_load_state_returns_none_when_nothing_persisted(session_factory):
    assert portfolio_repository.load_state(session_factory, "global") is None


def test_save_and_load_state_round_trip(session_factory):
    positions = {
        "AAPL": Position(symbol="AAPL", quantity=10.0, average_price=150.0),
        "MSFT": Position(symbol="MSFT", quantity=2.5, average_price=300.0),
    }
    portfolio_repository.save_snapshot(session_factory, "global", cash=5000.0, positions=positions, realized_pnl=42.5)

    loaded = portfolio_repository.load_state(session_factory, "global")

    assert loaded is not None
    cash, loaded_positions, realized_pnl = loaded
    assert cash == 5000.0
    assert realized_pnl == 42.5
    assert set(loaded_positions.keys()) == {"AAPL", "MSFT"}
    assert loaded_positions["AAPL"].quantity == 10.0
    assert loaded_positions["AAPL"].average_price == 150.0


def test_save_snapshot_overwrites_previous_positions_not_just_adds(session_factory):
    portfolio_repository.save_snapshot(
        session_factory, "global", cash=1000.0,
        positions={"AAPL": Position(symbol="AAPL", quantity=5.0, average_price=100.0)},
        realized_pnl=0.0,
    )
    # Position fully closed -- a fresh snapshot with an empty positions dict
    # must remove the stale AAPL row, not leave it dangling.
    portfolio_repository.save_snapshot(session_factory, "global", cash=1500.0, positions={}, realized_pnl=100.0)

    cash, positions, realized_pnl = portfolio_repository.load_state(session_factory, "global")
    assert cash == 1500.0
    assert positions == {}
    assert realized_pnl == 100.0


def test_state_is_isolated_per_market(session_factory):
    portfolio_repository.save_snapshot(session_factory, "global", cash=1000.0, positions={}, realized_pnl=0.0)
    portfolio_repository.save_snapshot(session_factory, "bist", cash=2000.0, positions={}, realized_pnl=0.0)

    assert portfolio_repository.load_state(session_factory, "global")[0] == 1000.0
    assert portfolio_repository.load_state(session_factory, "bist")[0] == 2000.0


def test_record_trade_and_load_recent_trades(session_factory):
    portfolio_repository.record_trade(session_factory, "global", "AAPL", "BUY", 150.0, 10.0, None)
    portfolio_repository.record_trade(session_factory, "global", "AAPL", "SELL", 160.0, 10.0, 100.0)
    portfolio_repository.record_trade(session_factory, "bist", "THYAO", "BUY", 300.0, 5.0, None)

    trades = portfolio_repository.load_recent_trades(session_factory, "global")

    assert len(trades) == 2
    assert trades[0].action == "SELL"  # newest first
    assert trades[0].realized_pnl == 100.0
    assert trades[1].action == "BUY"


def test_load_recent_trades_respects_limit(session_factory):
    for i in range(5):
        portfolio_repository.record_trade(session_factory, "global", "AAPL", "BUY", 100.0 + i, 1.0, None)

    trades = portfolio_repository.load_recent_trades(session_factory, "global", limit=2)
    assert len(trades) == 2
