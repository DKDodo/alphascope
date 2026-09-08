"""Persisted state for the manual (user-driven) paper portfolio -- separate
from the automated AutoTrader's own simulation_runs/simulation_positions
tables (see app/autotrader/db_models.py). PaperPortfolio itself stays a
pure, DB-unaware class; these tables are written/read by
portfolio_repository.py so a manual position survives a process restart.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.database import Base


class ManualPortfolioState(Base):
    """One row per market: the portfolio's cash and cumulative realized P&L.
    Open positions live in ManualPortfolioPosition below."""

    __tablename__ = "manual_portfolio_state"

    market: Mapped[str] = mapped_column(String(20), primary_key=True)
    cash: Mapped[float] = mapped_column(Float)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)


class ManualPortfolioPosition(Base):
    __tablename__ = "manual_portfolio_positions"

    market: Mapped[str] = mapped_column(String(20), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    quantity: Mapped[float] = mapped_column(Float)
    average_price: Mapped[float] = mapped_column(Float)


class ManualTradeLog(Base):
    __tablename__ = "manual_trade_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(20), index=True)
    symbol: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(4))  # BUY | SELL
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
