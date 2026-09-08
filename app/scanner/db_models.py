"""Persisted OHLCV bar history, so the scanner's rolling indicator window
survives a process restart (a redeploy, a desktop EXE relaunch) instead of
starting from zero every time. Only the raw bars are stored — indicators are
always recomputed from them, never persisted themselves.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.database import Base


class PersistedBar(Base):
    __tablename__ = "scanner_bars"
    __table_args__ = (
        Index("ix_scanner_bars_market_symbol_ts", "market", "symbol", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(20))
    symbol: Mapped[str] = mapped_column(String(20))
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
