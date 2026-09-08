"""Reads/writes tracked-signal outcome records (app.signals.tracking_db_models.
TrackedSignal). Plain sync SQLAlchemy calls, same pattern as bar_repository.py
and autotrader_service.py -- callers from async code should wrap these in
asyncio.to_thread() rather than awaiting them directly.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.signals.tracking_db_models import CHECKPOINT_DAYS, TrackedSignal

_MIN_SAMPLES_FOR_SUMMARY = 3


def record_signal_change(
    session_factory: sessionmaker[Session],
    market: str,
    symbol: str,
    signal: str,
    score: int,
    price: float,
    signaled_at: datetime,
) -> None:
    db = session_factory()
    try:
        db.add(
            TrackedSignal(
                market=market, symbol=symbol, signal=signal, score=score,
                price_at_signal=price, signaled_at=signaled_at,
            )
        )
        db.commit()
    finally:
        db.close()


def find_due_ids(
    session_factory: sessionmaker[Session], market: str, horizon_days: int, now: datetime
) -> list[int]:
    """IDs of TrackedSignal rows whose horizon_days checkpoint is due (enough
    time has passed since the signal) and not yet filled."""
    price_column = getattr(TrackedSignal, f"price_after_{horizon_days}d")
    cutoff = now - timedelta(days=horizon_days)
    db = session_factory()
    try:
        rows = (
            db.execute(
                select(TrackedSignal.id).where(
                    TrackedSignal.market == market,
                    TrackedSignal.signaled_at <= cutoff,
                    price_column.is_(None),
                )
            )
            .scalars()
            .all()
        )
        return list(rows)
    finally:
        db.close()


def get_symbol(session_factory: sessionmaker[Session], row_id: int) -> str | None:
    db = session_factory()
    try:
        row = db.get(TrackedSignal, row_id)
        return row.symbol if row is not None else None
    finally:
        db.close()


def fill_checkpoint(
    session_factory: sessionmaker[Session], row_id: int, horizon_days: int, current_price: float
) -> None:
    db = session_factory()
    try:
        row = db.get(TrackedSignal, row_id)
        if row is None:
            return
        return_pct = (
            round((current_price - row.price_at_signal) / row.price_at_signal * 100.0, 2)
            if row.price_at_signal
            else None
        )
        setattr(row, f"price_after_{horizon_days}d", round(current_price, 4))
        setattr(row, f"return_{horizon_days}d_pct", return_pct)
        db.commit()
    finally:
        db.close()


def get_performance_summary(session_factory: sessionmaker[Session], market: str) -> list[dict]:
    """One entry per (signal type, horizon) that has enough filled samples to
    mean something: average return %, sample count. Combinations with fewer
    than _MIN_SAMPLES_FOR_SUMMARY samples are omitted rather than shown as a
    misleading single-data-point average."""
    db = session_factory()
    try:
        rows = db.execute(select(TrackedSignal).where(TrackedSignal.market == market)).scalars().all()
    finally:
        db.close()

    summary: list[dict] = []
    for horizon in CHECKPOINT_DAYS:
        return_attr = f"return_{horizon}d_pct"
        by_signal: dict[str, list[float]] = {}
        for row in rows:
            value = getattr(row, return_attr)
            if value is None:
                continue
            by_signal.setdefault(row.signal, []).append(value)
        for signal, returns in by_signal.items():
            if len(returns) < _MIN_SAMPLES_FOR_SUMMARY:
                continue
            summary.append(
                {
                    "signal": signal,
                    "horizon_days": horizon,
                    "avg_return_pct": round(sum(returns) / len(returns), 2),
                    "sample_count": len(returns),
                }
            )
    return summary
