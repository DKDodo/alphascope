"""Reads/writes the persisted bar history (app.scanner.db_models.PersistedBar).

Plain sync SQLAlchemy calls, same as autotrader_service.py — callers from
async code should wrap these in asyncio.to_thread() rather than awaiting
them directly.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.scanner.db_models import PersistedBar
from app.scanner.scanner_engine import ROLLING_WINDOW


def save_bar(
    session_factory: sessionmaker[Session],
    market: str,
    symbol: str,
    timestamp: datetime,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    keep: int = ROLLING_WINDOW,
) -> None:
    db = session_factory()
    try:
        db.add(
            PersistedBar(
                market=market, symbol=symbol, timestamp=timestamp,
                open=open_, high=high, low=low, close=close, volume=volume,
            )
        )
        db.flush()
        _prune_old_bars(db, market, symbol, keep)
        db.commit()
    finally:
        db.close()


def _prune_old_bars(db: Session, market: str, symbol: str, keep: int) -> None:
    keep_ids = (
        select(PersistedBar.id)
        .where(PersistedBar.market == market, PersistedBar.symbol == symbol)
        .order_by(PersistedBar.timestamp.desc())
        .limit(keep)
    )
    db.execute(
        delete(PersistedBar).where(
            PersistedBar.market == market,
            PersistedBar.symbol == symbol,
            PersistedBar.id.notin_(keep_ids),
        )
    )


def load_recent_bars(
    session_factory: sessionmaker[Session],
    market: str,
    symbol: str,
    limit: int = ROLLING_WINDOW,
) -> list[PersistedBar]:
    """Returns up to `limit` bars for (market, symbol), oldest first — ready
    to feed straight into ScannerEngine.seed_bar() in order."""
    db = session_factory()
    try:
        rows = (
            db.execute(
                select(PersistedBar)
                .where(PersistedBar.market == market, PersistedBar.symbol == symbol)
                .order_by(PersistedBar.timestamp.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return list(reversed(rows))
    finally:
        db.close()
