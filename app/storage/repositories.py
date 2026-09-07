"""Persistence for scan history. Kept intentionally small for the MVP; the
scanner's live results live in memory (ScannerService) and are only mirrored
here for later review/backtesting."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.storage.database import Base


class ScanResultRecord(Base):
    __tablename__ = "scan_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    signal: Mapped[str] = mapped_column(String(20))
    score: Mapped[int] = mapped_column(Integer)
    price: Mapped[float]
    risk_level: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ScanResultRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, symbol: str, signal: str, score: int, price: float, risk_level: str) -> None:
        record = ScanResultRecord(
            symbol=symbol,
            signal=signal,
            score=score,
            price=price,
            risk_level=risk_level,
            created_at=datetime.utcnow(),
        )
        self._session.add(record)
        self._session.commit()

    def list_recent(self, symbol: str, limit: int = 50) -> list[ScanResultRecord]:
        return (
            self._session.query(ScanResultRecord)
            .filter(ScanResultRecord.symbol == symbol)
            .order_by(ScanResultRecord.created_at.desc())
            .limit(limit)
            .all()
        )
