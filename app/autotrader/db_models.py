"""Persisted state for the automated N-day paper trading simulation.

Persistence (not just in-memory, unlike the rest of the app's live state)
matters here specifically: a 7-day run must survive a server restart
(a Render free-tier sleep/wake cycle, a redeploy) without losing its
history or resetting its clock.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.storage.database import Base


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")  # RUNNING | COMPLETED
    started_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    initial_cash: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    currency_symbol: Mapped[str] = mapped_column(String(5), default="")

    positions: Mapped[list["SimulationPosition"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    trades: Mapped[list["SimulationTradeLog"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class SimulationPosition(Base):
    __tablename__ = "simulation_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("simulation_runs.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[float] = mapped_column(Float)
    average_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime)

    run: Mapped[SimulationRun] = relationship(back_populates="positions")


class SimulationTradeLog(Base):
    __tablename__ = "simulation_trade_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("simulation_runs.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(4))  # BUY | SELL
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(200))
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)

    run: Mapped[SimulationRun] = relationship(back_populates="trades")
