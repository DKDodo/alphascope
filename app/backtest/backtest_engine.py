"""Replays the live scoring/signal engine and a lightweight port of
AutoTraderService's entry/exit logic against historical daily bars -- lets
us ask "would this rule set have made money" in minutes instead of waiting
weeks for live signal-performance data (app/signals/tracking_repository.py)
to accumulate.

Reuses the SAME pure code the live system runs -- ScannerEngine,
SignalEngine, RiskEngine, dip_detector, PaperPortfolio -- fed historical
bars instead of live ticks, so this tests the actual rules rather than a
separate reimplementation that could subtly diverge. Entry/exit decision
constants are imported directly from autotrader_service.py so tuning one
tunes both; the decision FLOW is ported here as plain functions operating
on a lightweight dataclass instead of AutoTraderService's SQLAlchemy-bound
methods (that coupling isn't worth forcing onto a batch replay loop).

See BacktestResult.disclaimer (app/backtest/models.py) for what's
deliberately NOT replayed here: sector-diversification and Uzun Vadeli
Görünüm gates need point-in-time historical fundamentals that aren't
available for free, and the daily-trend confirmation gate is redundant
once the base timeframe already IS daily bars.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime, timezone
from statistics import mean, pstdev

from app.autotrader.autotrader_service import (
    AUTOTRADER_ENTRY_SCORE_MIN,
    AVOID_EXIT_STREAK_REQUIRED,
    DIP_ENTRY_MIN_CONFIDENCE,
    MAX_CONCURRENT_POSITIONS,
    MAX_DRAWDOWN_FRACTION,
    MAX_POSITION_ALLOCATION_FRACTION,
    MIN_TRADE_VALUE,
    PARTIAL_EXIT_FRACTION,
    RISK_PER_TRADE_FRACTION,
    TRAILING_STOP_ATR_MULTIPLIER,
    TRANSACTION_COST_RATE,
    VIX_ELEVATED_THRESHOLD,
    VIX_HIGH_THRESHOLD,
)
from app.backtest.historical_data import fetch_historical_series, fetch_single_series
from app.backtest.models import BacktestResult, BacktestTrade, EquityPoint
from app.core.logging import get_logger
from app.portfolio.paper_portfolio import PaperPortfolio
from app.risk.risk_engine import RiskEngine
from app.scanner.scanner_engine import ScannerEngine
from app.signals.models import SignalResult, SignalType
from app.signals.signal_engine import SignalEngine

logger = get_logger(__name__)

_TRADING_DAYS_PER_YEAR = 252


@dataclass
class _OpenPosition:
    stop_loss: float | None
    take_profit: float | None
    take_profit_2: float | None
    partial_exit_done: bool = False
    avoid_streak: int = 0


def run_backtest(
    market: str,
    symbols: list[str],
    ticker_suffix: str,
    benchmark_symbol: str | None,
    vix_available: bool,
    initial_cash: float,
    years: int,
) -> BacktestResult:
    series = fetch_historical_series(symbols, ticker_suffix, years)
    benchmark_series = fetch_single_series(benchmark_symbol, years) if benchmark_symbol else []
    vix_series = fetch_single_series("^VIX", years) if vix_available else []
    vix_by_date = {bar.timestamp.date(): bar.close for bar in vix_series}

    if not series:
        return _empty_result(market, years, initial_cash, benchmark_symbol, len(symbols))

    bars_by_date = {symbol: {bar.timestamp.date(): bar for bar in bars} for symbol, bars in series.items()}
    all_dates = sorted({d for by_date in bars_by_date.values() for d in by_date})

    scanner_engines = {symbol: ScannerEngine() for symbol in series}
    signal_engine = SignalEngine(risk_engine=RiskEngine())
    portfolio = PaperPortfolio(starting_cash=initial_cash)
    open_meta: dict[str, _OpenPosition] = {}
    trades: list[BacktestTrade] = []
    equity_curve: list[EquityPoint] = []
    peak_equity = initial_cash
    max_drawdown = 0.0

    for current_date in all_dates:
        signals_today: dict[str, SignalResult] = {}
        for symbol, engine in scanner_engines.items():
            bar = bars_by_date[symbol].get(current_date)
            if bar is not None:
                engine.seed_bar(symbol, bar.open, bar.high, bar.low, bar.close, bar.volume, bar.timestamp)
                portfolio.update_market_price(symbol, bar.close)
            ind = engine.compute_indicators(symbol)
            if ind is None:
                continue
            # daily_trend_up left at its None default -- redundant here, the
            # replay's base timeframe already IS the daily bar.
            signals_today[symbol] = signal_engine.evaluate(ind)

        _process_exits(portfolio, trades, open_meta, signals_today, current_date)

        equity = portfolio.snapshot().equity
        peak_equity = max(peak_equity, equity)
        drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
        max_drawdown = max(max_drawdown, drawdown)

        if drawdown < MAX_DRAWDOWN_FRACTION and len(open_meta) < MAX_CONCURRENT_POSITIONS:
            risk_multiplier = _risk_multiplier_from_vix(vix_by_date.get(current_date))
            _process_entries(portfolio, trades, open_meta, signals_today, risk_multiplier, current_date)

        equity_curve.append(EquityPoint(date=_to_datetime(current_date), equity=portfolio.snapshot().equity))

    _liquidate_remaining(portfolio, trades, open_meta, all_dates[-1])
    final_equity = portfolio.snapshot().equity
    equity_curve[-1] = EquityPoint(date=_to_datetime(all_dates[-1]), equity=final_equity)
    peak_equity = max(peak_equity, final_equity)
    max_drawdown = max(max_drawdown, (peak_equity - final_equity) / peak_equity if peak_equity > 0 else 0.0)

    return BacktestResult(
        market=market,
        years=years,
        start_date=_to_datetime(all_dates[0]),
        end_date=_to_datetime(all_dates[-1]),
        initial_cash=initial_cash,
        final_equity=round(final_equity, 2),
        total_return_pct=round((final_equity - initial_cash) / initial_cash * 100.0, 2) if initial_cash else 0.0,
        benchmark_symbol=benchmark_symbol,
        benchmark_return_pct=_benchmark_return_pct(benchmark_series),
        **_trade_stats(trades),
        max_drawdown_pct=round(max_drawdown * 100.0, 2),
        sharpe_ratio=_sharpe_ratio(equity_curve),
        equity_curve=equity_curve,
        trades=trades,
        symbols_included=len(series),
        symbols_skipped=len(symbols) - len(series),
    )


def _process_exits(
    portfolio: PaperPortfolio,
    trades: list[BacktestTrade],
    open_meta: dict[str, _OpenPosition],
    signals_today: dict[str, SignalResult],
    current_date: date_type,
) -> None:
    for symbol in list(open_meta.keys()):
        result = signals_today.get(symbol)
        if result is None:
            continue
        meta = open_meta[symbol]
        _update_trailing_stop(meta, result)
        _update_avoid_streak(meta, result.signal)

        if _should_take_partial_profit(meta, result.price):
            quantity = _current_quantity(portfolio, symbol) * PARTIAL_EXIT_FRACTION
            reason = f"Kısmi Kâr Alım (TP1) — kalan %{round((1 - PARTIAL_EXIT_FRACTION) * 100)} TP2'ye taşındı"
            _record_sell(trades, portfolio, symbol, quantity, result.price, reason, current_date)
            meta.partial_exit_done = True
            meta.take_profit = meta.take_profit_2
            continue

        reason = _exit_reason(meta, result.price, result.signal)
        if reason is not None:
            quantity = _current_quantity(portfolio, symbol)
            _record_sell(trades, portfolio, symbol, quantity, result.price, reason, current_date)
            del open_meta[symbol]


def _process_entries(
    portfolio: PaperPortfolio,
    trades: list[BacktestTrade],
    open_meta: dict[str, _OpenPosition],
    signals_today: dict[str, SignalResult],
    risk_multiplier: float,
    current_date: date_type,
) -> None:
    open_symbols = set(open_meta.keys())
    all_results = list(signals_today.values())

    trend_candidates = [
        r for r in all_results
        if r.score >= AUTOTRADER_ENTRY_SCORE_MIN and r.symbol not in open_symbols
    ]
    trend_candidates.sort(key=lambda r: r.score, reverse=True)
    trend_symbols = {r.symbol for r in trend_candidates}

    dip_candidates = [
        r for r in all_results
        if r.dip_opportunity is not None
        and r.dip_opportunity.confidence == DIP_ENTRY_MIN_CONFIDENCE
        and r.symbol not in open_symbols
        and r.symbol not in trend_symbols
    ]

    for result in trend_candidates + dip_candidates:
        if len(open_meta) >= MAX_CONCURRENT_POSITIONS:
            break
        cash = portfolio.snapshot().cash
        stop_loss = result.risk_analysis.stop_loss if result.risk_analysis else None
        take_profit = result.risk_analysis.take_profit_1 if result.risk_analysis else None
        take_profit_2 = result.risk_analysis.take_profit_2 if result.risk_analysis else None

        allocation = _position_size(cash, result.price, stop_loss, risk_multiplier)
        effective_cost = allocation * (1 + TRANSACTION_COST_RATE)
        if allocation < MIN_TRADE_VALUE or effective_cost > cash:
            continue

        quantity = allocation / result.price
        is_dip_entry = result.symbol not in trend_symbols
        reason = (
            f"Dip Fırsatı ({result.dip_opportunity.confidence.value} güven) — aşırı satım tepki alımı"
            if is_dip_entry
            else f"AutoTrader giriş eşiği aşıldı (skor {result.score}, görüntülenen sinyal: {result.signal.value})"
        )
        portfolio.buy(result.symbol, quantity, result.price * (1 + TRANSACTION_COST_RATE))
        trades.append(BacktestTrade(
            symbol=result.symbol, action="BUY", date=_to_datetime(current_date),
            price=result.price, quantity=quantity, reason=reason,
        ))
        open_meta[result.symbol] = _OpenPosition(
            stop_loss=stop_loss, take_profit=take_profit, take_profit_2=take_profit_2,
        )


def _liquidate_remaining(
    portfolio: PaperPortfolio, trades: list[BacktestTrade], open_meta: dict[str, _OpenPosition], last_date: date_type
) -> None:
    for symbol in list(open_meta.keys()):
        snap = portfolio.snapshot()
        position = next((p for p in snap.positions if p.symbol == symbol), None)
        if position is None:
            continue
        price = position.current_price if position.current_price is not None else position.average_price
        _record_sell(
            trades, portfolio, symbol, position.quantity, price,
            "Backtest dönemi sona erdi (mark-to-market kapanış)", last_date,
        )
        del open_meta[symbol]


# -- ported, backtest-local versions of AutoTraderService's decision logic ----------

def _update_trailing_stop(meta: _OpenPosition, result: SignalResult) -> None:
    if meta.stop_loss is None or result.risk_analysis is None:
        return
    atr = result.risk_analysis.atr
    if atr <= 0:
        return
    trailing_candidate = result.price - atr * TRAILING_STOP_ATR_MULTIPLIER
    if trailing_candidate > meta.stop_loss:
        meta.stop_loss = trailing_candidate


def _should_take_partial_profit(meta: _OpenPosition, price: float) -> bool:
    return (
        not meta.partial_exit_done
        and meta.take_profit_2 is not None
        and meta.take_profit is not None
        and price >= meta.take_profit
    )


def _update_avoid_streak(meta: _OpenPosition, signal: SignalType) -> None:
    if signal == SignalType.AVOID:
        meta.avoid_streak += 1
    else:
        meta.avoid_streak = 0


def _exit_reason(meta: _OpenPosition, price: float, signal: SignalType) -> str | None:
    if meta.stop_loss is not None and price <= meta.stop_loss:
        return "Zarar-kes seviyesine ulaşıldı"
    if meta.take_profit is not None and price >= meta.take_profit:
        return "Kâr-al seviyesine ulaşıldı"
    if meta.avoid_streak >= AVOID_EXIT_STREAK_REQUIRED:
        return f"Sinyal {AVOID_EXIT_STREAK_REQUIRED} ardışık kontrolde KAÇININ'da kaldı"
    return None


def _risk_multiplier_from_vix(vix: float | None) -> float:
    if vix is None:
        return 1.0
    if vix >= VIX_HIGH_THRESHOLD:
        return 0.25
    if vix >= VIX_ELEVATED_THRESHOLD:
        return 0.5
    return 1.0


def _position_size(cash: float, entry_price: float, stop_loss: float | None, risk_multiplier: float) -> float:
    max_position_value = cash * MAX_POSITION_ALLOCATION_FRACTION
    if stop_loss is None or stop_loss >= entry_price:
        return max_position_value
    risk_per_share = entry_price - stop_loss
    risk_budget = cash * RISK_PER_TRADE_FRACTION * risk_multiplier
    return min((risk_budget / risk_per_share) * entry_price, max_position_value)


# -- bookkeeping helpers -------------------------------------------------------------

def _current_quantity(portfolio: PaperPortfolio, symbol: str) -> float:
    position = next((p for p in portfolio.snapshot().positions if p.symbol == symbol), None)
    return position.quantity if position is not None else 0.0


def _record_sell(
    trades: list[BacktestTrade], portfolio: PaperPortfolio, symbol: str,
    quantity: float, price: float, reason: str, current_date: date_type,
) -> None:
    snap_before = portfolio.snapshot()
    avg_price = next((p.average_price for p in snap_before.positions if p.symbol == symbol), price)
    net_price = price * (1 - TRANSACTION_COST_RATE)
    portfolio.sell(symbol, quantity, net_price)
    pnl = round(portfolio.snapshot().realized_pnl - snap_before.realized_pnl, 2)
    return_pct = round((net_price - avg_price) / avg_price * 100.0, 2) if avg_price else None
    trades.append(BacktestTrade(
        symbol=symbol, action="SELL", date=_to_datetime(current_date), price=price,
        quantity=quantity, reason=reason, realized_pnl=pnl, return_pct=return_pct,
    ))


def _to_datetime(d: date_type) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _benchmark_return_pct(benchmark_series) -> float | None:
    if len(benchmark_series) < 2:
        return None
    first, last = benchmark_series[0].close, benchmark_series[-1].close
    return round((last - first) / first * 100.0, 2) if first else None


def _trade_stats(trades: list[BacktestTrade]) -> dict:
    closed = [t for t in trades if t.action == "SELL" and t.realized_pnl is not None]
    winning = [t for t in closed if t.realized_pnl > 0]
    losing = [t for t in closed if t.realized_pnl <= 0]
    win_returns = [t.return_pct for t in winning if t.return_pct is not None]
    loss_returns = [t.return_pct for t in losing if t.return_pct is not None]
    return {
        "trade_count": len(trades),
        "winning_trades": len(winning),
        "losing_trades": len(losing),
        "win_rate_pct": round(len(winning) / len(closed) * 100.0, 2) if closed else None,
        "avg_win_pct": round(mean(win_returns), 2) if win_returns else None,
        "avg_loss_pct": round(mean(loss_returns), 2) if loss_returns else None,
    }


def _sharpe_ratio(equity_curve: list[EquityPoint]) -> float | None:
    """Simplified (no risk-free-rate subtraction) annualized Sharpe from
    daily equity returns -- a reasonable simplification for an internal
    decision-support tool, not a precise risk-adjusted-return figure."""
    if len(equity_curve) < 3:
        return None
    returns = []
    for prev, curr in zip(equity_curve, equity_curve[1:]):
        if prev.equity > 0:
            returns.append((curr.equity - prev.equity) / prev.equity)
    if len(returns) < 2:
        return None
    daily_std = pstdev(returns)
    if daily_std == 0:
        return None
    return round(mean(returns) / daily_std * (_TRADING_DAYS_PER_YEAR ** 0.5), 2)


def _empty_result(
    market: str, years: int, initial_cash: float, benchmark_symbol: str | None, symbols_requested: int
) -> BacktestResult:
    return BacktestResult(
        market=market, years=years, initial_cash=initial_cash, final_equity=initial_cash,
        total_return_pct=0.0, benchmark_symbol=benchmark_symbol, trade_count=0,
        winning_trades=0, losing_trades=0, max_drawdown_pct=0.0, equity_curve=[], trades=[],
        symbols_included=0, symbols_skipped=symbols_requested,
    )
