"""Reads/writes the persisted manual-portfolio state (app.portfolio.db_models).

Plain sync SQLAlchemy calls, same pattern as bar_repository.py and
autotrader_service.py -- callers from async code should wrap these in
asyncio.to_thread() rather than awaiting them directly. PaperPortfolio
itself never imports this module (it stays a pure, DB-unaware class) --
only the API routes that call buy()/sell() do.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.portfolio.db_models import ManualPortfolioPosition, ManualPortfolioState, ManualTradeLog
from app.portfolio.models import Position


def load_state(
    session_factory: sessionmaker[Session], market: str
) -> tuple[float, dict[str, Position], float] | None:
    """Returns (cash, positions_by_symbol, realized_pnl) if this market has
    persisted manual-portfolio state, else None (fresh start -- the caller
    keeps PaperPortfolio's constructor default)."""
    db = session_factory()
    try:
        state = db.get(ManualPortfolioState, market)
        if state is None:
            return None
        rows = db.execute(
            select(ManualPortfolioPosition).where(ManualPortfolioPosition.market == market)
        ).scalars().all()
        positions = {
            row.symbol: Position(symbol=row.symbol, quantity=row.quantity, average_price=row.average_price)
            for row in rows
        }
        return state.cash, positions, state.realized_pnl
    finally:
        db.close()


def save_snapshot(
    session_factory: sessionmaker[Session],
    market: str,
    cash: float,
    positions: dict[str, Position],
    realized_pnl: float,
) -> None:
    """Overwrites the persisted state with the portfolio's current
    in-memory contents -- called after every successful buy()/sell()."""
    db = session_factory()
    try:
        state = db.get(ManualPortfolioState, market)
        if state is None:
            state = ManualPortfolioState(market=market, cash=cash, realized_pnl=realized_pnl)
            db.add(state)
        else:
            state.cash = cash
            state.realized_pnl = realized_pnl

        db.execute(delete(ManualPortfolioPosition).where(ManualPortfolioPosition.market == market))
        for position in positions.values():
            db.add(ManualPortfolioPosition(
                market=market, symbol=position.symbol,
                quantity=position.quantity, average_price=position.average_price,
            ))
        db.commit()
    finally:
        db.close()


def record_trade(
    session_factory: sessionmaker[Session],
    market: str,
    symbol: str,
    action: str,
    price: float,
    quantity: float,
    realized_pnl: float | None,
) -> None:
    db = session_factory()
    try:
        db.add(ManualTradeLog(
            market=market, symbol=symbol, action=action, price=price,
            quantity=quantity, realized_pnl=realized_pnl, timestamp=datetime.now(timezone.utc),
        ))
        db.commit()
    finally:
        db.close()


def load_recent_trades(
    session_factory: sessionmaker[Session], market: str, limit: int = 50
) -> list[ManualTradeLog]:
    db = session_factory()
    try:
        return list(
            db.execute(
                select(ManualTradeLog)
                .where(ManualTradeLog.market == market)
                .order_by(ManualTradeLog.id.desc())
                .limit(limit)
            ).scalars().all()
        )
    finally:
        db.close()
