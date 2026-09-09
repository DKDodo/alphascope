"""Backtest data models. A backtest is a decision-support estimate, not a
guarantee — see BacktestResult.disclaimer for the honest limitations of
replaying the live scoring rules against historical daily bars.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class HistoricalBar(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class BacktestRequest(BaseModel):
    years: int = 3
    initial_cash: float = 10_000.0


class BacktestTrade(BaseModel):
    symbol: str
    action: str  # BUY | SELL
    date: datetime
    price: float
    quantity: float
    reason: str
    realized_pnl: float | None = None
    return_pct: float | None = None  # SELL rows only


class EquityPoint(BaseModel):
    date: datetime
    equity: float


class BacktestResult(BaseModel):
    market: str
    years: int
    start_date: datetime | None = None
    end_date: datetime | None = None
    initial_cash: float
    final_equity: float
    total_return_pct: float
    benchmark_symbol: str | None = None
    benchmark_return_pct: float | None = None
    trade_count: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float | None = None
    avg_win_pct: float | None = None
    avg_loss_pct: float | None = None
    max_drawdown_pct: float
    sharpe_ratio: float | None = None
    equity_curve: list[EquityPoint]
    trades: list[BacktestTrade]
    symbols_included: int
    symbols_skipped: int
    disclaimer: str = (
        "Bu geriye dönük bir simülasyondur; geçmiş performans gelecekteki "
        "sonuçları garanti etmez ve yatırım tavsiyesi değildir. Canlı "
        "sistemin dakikalık penceresinden farklı olarak günlük bar üzerinde "
        "çalışır; sektör çeşitlendirme, Uzun Vadeli Görünüm ve haber "
        "duyarlılığı filtreleri (geçmişe dönük nokta-zamanlı temel veri ya "
        "da haber arşivi bulunmadığından) ve günlük trend onayı (zaten "
        "günlük bar kullanıldığından gereksiz) uygulanmaz. VWAP günlük "
        "barda o günün ortalama fiyatına dejenere olur."
    )
