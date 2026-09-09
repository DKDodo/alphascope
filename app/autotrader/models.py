"""API-facing models for the automated simulation. Fully separate from the
manual PaperPortfolio — this is a self-driving simulation the system runs
against its own signals, not a portfolio the user trades by hand."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator


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
    # Null when this run uses the default ATR-based stop/target sizing;
    # set when the user chose fixed percentages at start time instead (see
    # StartSimulationRequest below) -- shown in the UI so it's clear which
    # mode a run is in.
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
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
    # gt=0 + allow_inf_nan=False: a zero/negative initial_cash left a run
    # permanently stuck "RUNNING" with no trade ever clearing MIN_TRADE_VALUE
    # (and start_run() refuses a new run while one is active, so this locked
    # out the whole market); a non-positive duration_days would produce an
    # ends_at at or before started_at.
    initial_cash: float = Field(default=10_000.0, gt=0, allow_inf_nan=False)
    duration_days: float = Field(default=7.0, gt=0, allow_inf_nan=False)
    # Optional: fixed-percentage stop-loss/take-profit instead of the
    # default ATR-based (volatility-adaptive) sizing -- e.g. 5.0 = 5%. Leave
    # both unset (None) to keep today's ATR-based behavior unchanged. gt=0
    # when set: a 0% stop_loss_pct put the initial stop at the entry price
    # itself, force-closing every position one tick after it opened.
    stop_loss_pct: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    take_profit_pct: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _stop_and_target_pct_must_be_paired(self) -> "StartSimulationRequest":
        # _process_entries() only switches a run to fixed-percentage sizing
        # when BOTH are set; a request setting only one would otherwise
        # silently size new positions off ATR while _update_trailing_stop()
        # (which only checks stop_loss_pct) trails them at an unrelated
        # fixed-percentage distance.
        if (self.stop_loss_pct is None) != (self.take_profit_pct is None):
            raise ValueError("stop_loss_pct ve take_profit_pct birlikte verilmeli ya da ikisi de boş bırakılmalı.")
        return self
