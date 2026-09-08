from __future__ import annotations

import pytest

from app.core.exceptions import RiskCalculationError
from app.portfolio.models import Position
from app.portfolio.paper_portfolio import PaperPortfolio


def test_buy_deducts_cash_and_opens_a_position():
    pf = PaperPortfolio(starting_cash=10_000.0)
    pf.buy("AAPL", 10.0, 100.0)

    snap = pf.snapshot()
    assert snap.cash == 9_000.0
    assert len(snap.positions) == 1
    assert snap.positions[0].quantity == 10.0
    assert snap.positions[0].average_price == 100.0


def test_buy_averages_price_across_multiple_purchases():
    pf = PaperPortfolio(starting_cash=10_000.0)
    pf.buy("AAPL", 10.0, 100.0)
    pf.buy("AAPL", 10.0, 120.0)

    position = pf.snapshot().positions[0]
    assert position.quantity == 20.0
    assert position.average_price == pytest.approx(110.0)


def test_buy_rejects_insufficient_cash():
    pf = PaperPortfolio(starting_cash=100.0)
    with pytest.raises(RiskCalculationError):
        pf.buy("AAPL", 10.0, 100.0)


def test_sell_realizes_pnl_and_returns_cash():
    pf = PaperPortfolio(starting_cash=10_000.0)
    pf.buy("AAPL", 10.0, 100.0)
    pf.sell("AAPL", 10.0, 110.0)

    snap = pf.snapshot()
    assert snap.cash == pytest.approx(10_000.0 + 100.0)  # bought 1000, sold 1100
    assert snap.realized_pnl == pytest.approx(100.0)
    assert len(snap.positions) == 0


def test_sell_rejects_overselling():
    pf = PaperPortfolio(starting_cash=10_000.0)
    pf.buy("AAPL", 5.0, 100.0)
    with pytest.raises(RiskCalculationError):
        pf.sell("AAPL", 10.0, 100.0)


def test_unrealized_pnl_reflects_live_price_before_any_sale():
    pf = PaperPortfolio(starting_cash=10_000.0)
    pf.buy("AAPL", 10.0, 100.0)
    pf.update_market_price("AAPL", 130.0)

    snap = pf.snapshot()
    assert snap.unrealized_pnl == pytest.approx(300.0)  # (130-100)*10, without selling anything


def test_restore_state_overwrites_cash_positions_and_realized_pnl():
    pf = PaperPortfolio(starting_cash=10_000.0)
    pf.buy("AAPL", 10.0, 100.0)  # state that must be fully replaced, not merged

    pf.restore_state(
        cash=5_000.0,
        positions={"MSFT": Position(symbol="MSFT", quantity=3.0, average_price=200.0)},
        realized_pnl=250.0,
    )

    snap = pf.snapshot()
    assert snap.cash == 5_000.0
    assert snap.realized_pnl == 250.0
    assert len(snap.positions) == 1
    assert snap.positions[0].symbol == "MSFT"


def test_restored_portfolio_continues_trading_normally():
    pf = PaperPortfolio(starting_cash=100.0)
    pf.restore_state(
        cash=10_000.0,
        positions={"AAPL": Position(symbol="AAPL", quantity=5.0, average_price=100.0)},
        realized_pnl=0.0,
    )

    pf.sell("AAPL", 5.0, 120.0)  # must operate against the restored position, not a fresh empty one

    snap = pf.snapshot()
    assert snap.realized_pnl == pytest.approx(100.0)
    assert len(snap.positions) == 0
