"""API-facing models for the automated simulation. Fully separate from the
manual PaperPortfolio — this is a self-driving simulation the system runs
against its own signals, not a portfolio the user trades by hand."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class SimulationStatusValue(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


class SimulationPositionOut(BaseModel):
    symbol: str
    quantity: float
    average_price: float
    current_price: float | None
    unrealized_pnl: float | None
    stop_loss: float | None
    take_profit: float | None


class SimulationTradeOut(BaseModel):
    symbol: str
    action: str
    price: float
    quantity: float
    reason: str
    realized_pnl: float | None
    timestamp: datetime


class SimulationStatusOut(BaseModel):
    status: SimulationStatusValue
    market: str
    currency_symbol: str
    started_at: datetime | None = None
    ends_at: datetime | None = None
    completed_at: datetime | None = None
    days_remaining: float | None = None
    initial_cash: float | None = None
    cash: float | None = None
    equity: float | None = None
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None
    total_return_pct: float | None = None
    peak_equity: float | None = None
    drawdown_pct: float | None = None  # % below peak_equity right now
    trading_paused: bool = False  # true once drawdown_pct >= the circuit breaker threshold
    trade_count: int = 0
    positions: list[SimulationPositionOut] = []
    recent_trades: list[SimulationTradeOut] = []
    disclaimer: str = (
        "Bu tamamen sanal (kağıt üzerinde) bir simülasyondur; gerçek para veya "
        "gerçek emir kullanılmaz. Sistem kendi kurallı sinyallerine göre otomatik "
        "karar verir — bu bir yatırım tavsiyesi değildir ve geçmiş/kısa vadeli "
        "simülasyon performansı gelecekteki sonuçları garanti etmez."
    )


class StartSimulationRequest(BaseModel):
    initial_cash: float = 10_000.0
    duration_days: float = 7.0
