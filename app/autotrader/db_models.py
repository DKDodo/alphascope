"""Persisted state for the automated N-day paper trading simulation.

Persistence (not just in-memory, unlike the rest of the app's live state)
matters here specifically: a 7-day run must survive a server restart
(a Render free-tier sleep/wake cycle, a redeploy) without losing its
history or resetting its clock.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
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
    # Highest equity (cash + open positions' market value) seen so far this
    # run -- lets AutoTraderService pause new entries after a drawdown from
    # that peak (see MAX_DRAWDOWN_FRACTION). Added after this table already
    # existed in production; see Database.ensure_columns().
    peak_equity: Mapped[float] = mapped_column(Float, default=0.0)
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
    # "Current active target" -- starts as TP1; once the partial exit fires
    # it's overwritten with take_profit_2's value for the remaining half
    # (see AutoTraderService._partial_sell), so exit-checking code only
    # ever needs to compare price against this one field.
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The second-tier target, staged at entry -- NULL for positions opened
    # before this feature shipped, which correctly skips partial-exit
    # handling for them (see Database.ensure_columns()).
    take_profit_2: Mapped[float | None] = mapped_column(Float, nullable=True)
    partial_exit_done: Mapped[bool] = mapped_column(Boolean, default=False)
    # Consecutive exit-check passes (see AutoTraderService._update_avoid_streak)
    # the signal has read AVOID -- exit only fires once this persists for
    # AVOID_EXIT_STREAK_REQUIRED passes, instead of on a single noisy reading.
    avoid_streak: Mapped[int] = mapped_column(Integer, default=0)
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
