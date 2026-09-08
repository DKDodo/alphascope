"""Persisted record of every signal *change* the scanner has produced, plus
its price N days later once that much time has passed. This is how
AlphaScope answers "do STRONG_BUY_SETUP calls actually do better than
AVOID calls?" from its own live history, rather than asking the user to
just trust the scoring rules in scoring.py.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.database import Base

# Kept in sync with tracking_repository.CHECKPOINT_DAYS.
CHECKPOINT_DAYS: tuple[int, ...] = (5, 10, 20)


class TrackedSignal(Base):
    __tablename__ = "tracked_signals"
    __table_args__ = (
        Index("ix_tracked_signals_market_symbol", "market", "symbol"),
        Index("ix_tracked_signals_signaled_at", "signaled_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(20))
    symbol: Mapped[str] = mapped_column(String(20))
    signal: Mapped[str] = mapped_column(String(20))  # SignalType value at the moment it changed to this
    score: Mapped[int] = mapped_column(Integer)
    price_at_signal: Mapped[float] = mapped_column(Float)
    signaled_at: Mapped[datetime] = mapped_column(DateTime)

    price_after_5d: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_5d_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_after_10d: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_10d_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_after_20d: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_20d_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
