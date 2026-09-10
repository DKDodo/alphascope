from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

import pytest

from app.autotrader.autotrader_service import AVOID_EXIT_STREAK_REQUIRED
from app.backtest import backtest_engine
from app.backtest.backtest_engine import (
    _TRADING_DAYS_PER_YEAR,
    _OpenPosition,
    _benchmark_return_pct,
    _exit_reason,
    _position_size,
    _process_entries,
    _process_exits,
    _risk_multiplier_from_vix,
    _sharpe_ratio,
    _should_take_partial_profit,
    _trade_stats,
    _update_avoid_streak,
    _update_trailing_stop,
    run_backtest,
)
from app.backtest.models import BacktestTrade, EquityPoint, HistoricalBar
from app.portfolio.paper_portfolio import PaperPortfolio
from app.risk.risk_engine import RiskAnalysis, RiskLevel
from app.signals.models import CategoryScores, SignalResult, SignalType


def _signal(
    price: float, atr: float = 1.0, signal: SignalType = SignalType.NEUTRAL, symbol: str = "AAPL", score: int = 90
) -> SignalResult:
    return SignalResult(
        symbol=symbol, price=price, score=score, signal=signal, reasons=[], risk_level=RiskLevel.MEDIUM,
        category_scores=CategoryScores(trend=10, momentum=10, volume=10, price_action=10, risk_reward=10),
        risk_analysis=RiskAnalysis(
            entry_price=price, stop_loss=price - 5, take_profit_1=price + 10, take_profit_2=price + 20,
            atr=atr, risk_per_share=5, reward_per_share_tp1=10, risk_reward_ratio=2.0, risk_level=RiskLevel.MEDIUM,
        ),
    )


def _bars(prices: list[float], base_volume: float = 1_000_000.0) -> list[HistoricalBar]:
    start = datetime(2022, 1, 3, tzinfo=timezone.utc)
    bars = []
    for i, price in enumerate(prices):
        bars.append(HistoricalBar(
            timestamp=start + timedelta(days=i), open=price, high=price + 0.5, low=price - 0.5,
            close=price, volume=base_volume,
        ))
    return bars


def _realistic_uptrend_bars(days: int, base_volume: float = 1_000_000.0, seed: int = 42) -> list[HistoricalBar]:
    """A net-upward series with real day-to-day noise, occasional down days,
    and periodic volume spikes -- unlike a perfectly linear/constant-volume
    series (which saturates RSI at 100 and never elevates volume_ratio
    above 1.0), this can actually clear score_trend/momentum/volume/
    price_action's thresholds the way real market data does."""
    rng = random.Random(seed)
    start = datetime(2022, 1, 3, tzinfo=timezone.utc)
    bars = []
    price = 100.0
    for i in range(days):
        daily_change = rng.uniform(-0.4, 1.1)
        open_ = price
        close = max(1.0, price + daily_change)
        high = max(open_, close) + rng.uniform(0.3, 1.2)
        low = min(open_, close) - rng.uniform(0.3, 1.2)
        volume = base_volume * rng.uniform(0.7, 1.3)
        if i % 12 == 0:
            volume *= 2.8  # occasional participation spike
        bars.append(HistoricalBar(
            timestamp=start + timedelta(days=i), open=open_, high=high, low=low, close=close, volume=volume,
        ))
        price = close
    return bars


# -- pure decision-logic helpers ------------------------------------------------------

def test_position_size_scales_with_stop_distance():
    tight = _position_size(cash=10_000.0, entry_price=100.0, stop_loss=95.0, risk_multiplier=1.0)
    wide = _position_size(cash=10_000.0, entry_price=100.0, stop_loss=80.0, risk_multiplier=1.0)
    assert tight == pytest.approx(2_000.0)  # risk-based (4000) hits the flat 20% cap
    assert wide < tight  # wider stop -> smaller position for the same risk


def test_position_size_falls_back_to_flat_cap_without_a_stop():
    assert _position_size(cash=10_000.0, entry_price=100.0, stop_loss=None, risk_multiplier=1.0) == pytest.approx(2_000.0)


def test_risk_multiplier_from_vix_thresholds():
    assert _risk_multiplier_from_vix(None) == 1.0
    assert _risk_multiplier_from_vix(12.0) == 1.0
    assert _risk_multiplier_from_vix(25.0) == 0.5
    assert _risk_multiplier_from_vix(35.0) == 0.25


def test_exit_reason_stop_loss_and_take_profit_are_instant():
    meta = _OpenPosition(stop_loss=95.0, take_profit=110.0, take_profit_2=None)
    assert _exit_reason(meta, 94.0, SignalType.NEUTRAL) == "Zarar-kes seviyesine ulaşıldı"
    assert _exit_reason(meta, 111.0, SignalType.NEUTRAL) == "Kâr-al seviyesine ulaşıldı"
    assert _exit_reason(meta, 100.0, SignalType.NEUTRAL) is None


def test_avoid_streak_requires_persistence_before_exiting():
    meta = _OpenPosition(stop_loss=95.0, take_profit=110.0, take_profit_2=None)

    # A single noisy AVOID reading must not close the position by itself.
    _update_avoid_streak(meta, SignalType.AVOID)
    assert meta.avoid_streak == 1
    assert _exit_reason(meta, 100.0, SignalType.AVOID) is None

    # ...but a genuine reversal that persists does exit, once it reaches
    # AVOID_EXIT_STREAK_REQUIRED consecutive checks.
    for _ in range(AVOID_EXIT_STREAK_REQUIRED - 1):
        _update_avoid_streak(meta, SignalType.AVOID)
    assert meta.avoid_streak == AVOID_EXIT_STREAK_REQUIRED
    assert _exit_reason(meta, 100.0, SignalType.AVOID) is not None


def test_avoid_streak_resets_the_moment_the_signal_recovers():
    meta = _OpenPosition(stop_loss=95.0, take_profit=110.0, take_profit_2=None)
    for _ in range(AVOID_EXIT_STREAK_REQUIRED - 1):
        _update_avoid_streak(meta, SignalType.AVOID)
    assert meta.avoid_streak == AVOID_EXIT_STREAK_REQUIRED - 1

    _update_avoid_streak(meta, SignalType.NEUTRAL)  # one non-AVOID reading resets the count

    assert meta.avoid_streak == 0
    assert _exit_reason(meta, 100.0, SignalType.NEUTRAL) is None


def test_should_take_partial_profit_requires_tp2_and_not_already_done():
    meta = _OpenPosition(stop_loss=95.0, take_profit=110.0, take_profit_2=120.0)
    assert _should_take_partial_profit(meta, 111.0) is True
    assert _should_take_partial_profit(meta, 109.0) is False  # hasn't reached TP1 yet

    meta_no_tp2 = _OpenPosition(stop_loss=95.0, take_profit=110.0, take_profit_2=None)
    assert _should_take_partial_profit(meta_no_tp2, 111.0) is False  # old-style position, no second tier

    meta_done = _OpenPosition(stop_loss=95.0, take_profit=120.0, take_profit_2=120.0, partial_exit_done=True)
    assert _should_take_partial_profit(meta_done, 121.0) is False  # already took the partial


def test_trailing_stop_only_ratchets_up():
    meta = _OpenPosition(stop_loss=95.0, take_profit=200.0, take_profit_2=None)
    _update_trailing_stop(meta, _signal(price=110.0, atr=1.0))
    assert meta.stop_loss == pytest.approx(108.5)  # 110 - 1.5*1.0

    _update_trailing_stop(meta, _signal(price=109.0, atr=1.0))  # would-be candidate 107.5, below current
    assert meta.stop_loss == pytest.approx(108.5)  # unchanged, never moves down


def test_benchmark_return_pct():
    assert _benchmark_return_pct(_bars([100.0, 110.0, 121.0])) == pytest.approx(21.0)
    assert _benchmark_return_pct(_bars([100.0])) is None
    assert _benchmark_return_pct([]) is None


def test_trade_stats_win_rate_and_averages():
    trades = [
        BacktestTrade(symbol="A", action="BUY", date=datetime.now(timezone.utc), price=100, quantity=1, reason="x"),
        BacktestTrade(symbol="A", action="SELL", date=datetime.now(timezone.utc), price=110, quantity=1,
                      reason="x", realized_pnl=10.0, return_pct=10.0),
        BacktestTrade(symbol="B", action="BUY", date=datetime.now(timezone.utc), price=100, quantity=1, reason="x"),
        BacktestTrade(symbol="B", action="SELL", date=datetime.now(timezone.utc), price=95, quantity=1,
                      reason="x", realized_pnl=-5.0, return_pct=-5.0),
    ]
    stats = _trade_stats(trades)
    assert stats["trade_count"] == 4
    assert stats["winning_trades"] == 1
    assert stats["losing_trades"] == 1
    assert stats["win_rate_pct"] == pytest.approx(50.0)
    assert stats["avg_win_pct"] == pytest.approx(10.0)
    assert stats["avg_loss_pct"] == pytest.approx(-5.0)


def test_trade_stats_with_no_closed_trades():
    stats = _trade_stats([])
    assert stats["win_rate_pct"] is None
    assert stats["avg_win_pct"] is None


def test_sharpe_ratio_none_for_flat_equity_curve():
    now = datetime.now(timezone.utc)
    curve = [EquityPoint(date=now + timedelta(days=i), equity=10_000.0) for i in range(5)]
    # zero variance -> undefined, not a divide-by-zero crash
    assert _sharpe_ratio(curve, _TRADING_DAYS_PER_YEAR) is None


def test_sharpe_ratio_positive_for_a_steadily_rising_curve():
    now = datetime.now(timezone.utc)
    curve = [EquityPoint(date=now + timedelta(days=i), equity=10_000.0 * (1.001 ** i)) for i in range(30)]
    sharpe = _sharpe_ratio(curve, _TRADING_DAYS_PER_YEAR)
    assert sharpe is not None and sharpe > 0


def test_sharpe_ratio_uses_365_day_annualization_for_crypto():
    # Crypto trades every calendar day (no exchange sessions), so its Sharpe
    # must scale by sqrt(365), not the equity-market sqrt(252) -- otherwise
    # it's systematically understated by ~17%.
    now = datetime.now(timezone.utc)
    curve = [EquityPoint(date=now + timedelta(days=i), equity=10_000.0 * (1.001 ** i)) for i in range(30)]
    equity_sharpe = _sharpe_ratio(curve, _TRADING_DAYS_PER_YEAR)
    crypto_sharpe = _sharpe_ratio(curve, 365)
    assert crypto_sharpe > equity_sharpe > 0
    assert crypto_sharpe == pytest.approx(equity_sharpe * (365 / _TRADING_DAYS_PER_YEAR) ** 0.5)


# -- entry/exit orchestration, driven with hand-crafted signals (precise,
# not coupled to the real scoring engine's exact thresholds) ------------------------

def test_process_entries_buys_on_a_strong_signal():
    portfolio = PaperPortfolio(starting_cash=10_000.0)
    trades: list[BacktestTrade] = []
    open_meta: dict[str, _OpenPosition] = {}
    signals_today = {"AAPL": _signal(100.0, signal=SignalType.STRONG_BUY_SETUP)}

    _process_entries(portfolio, trades, open_meta, signals_today, risk_multiplier=1.0, current_date=date(2022, 1, 3))

    assert "AAPL" in open_meta
    assert len(trades) == 1 and trades[0].action == "BUY"
    assert portfolio.snapshot().cash < 10_000.0


def test_process_entries_respects_max_concurrent_positions():
    portfolio = PaperPortfolio(starting_cash=100_000.0)
    trades: list[BacktestTrade] = []
    open_meta: dict[str, _OpenPosition] = {}
    signals_today = {
        f"SYM{i}": _signal(100.0, signal=SignalType.STRONG_BUY_SETUP).model_copy(update={"symbol": f"SYM{i}"})
        for i in range(10)
    }

    _process_entries(portfolio, trades, open_meta, signals_today, risk_multiplier=1.0, current_date=date(2022, 1, 3))

    from app.autotrader.autotrader_service import MAX_CONCURRENT_POSITIONS
    assert len(open_meta) == MAX_CONCURRENT_POSITIONS


def test_process_entries_skips_a_dust_sized_allocation():
    # cash=1.0, risk_multiplier=0.25 -> risk_budget=0.005, position_value=0.1,
    # well under MIN_TRADE_VALUE (1.0) -- must be skipped, not executed as a
    # near-zero trade.
    portfolio = PaperPortfolio(starting_cash=1.0)
    trades: list[BacktestTrade] = []
    open_meta: dict[str, _OpenPosition] = {}
    signals_today = {"AAPL": _signal(100.0, signal=SignalType.STRONG_BUY_SETUP)}

    _process_entries(portfolio, trades, open_meta, signals_today, risk_multiplier=0.25, current_date=date(2022, 1, 3))

    assert "AAPL" not in open_meta
    assert trades == []


def test_process_exits_sells_on_stop_loss():
    portfolio = PaperPortfolio(starting_cash=10_000.0)
    portfolio.buy("AAPL", 10.0, 100.0)
    trades: list[BacktestTrade] = []
    open_meta = {"AAPL": _OpenPosition(stop_loss=95.0, take_profit=200.0, take_profit_2=None)}
    signals_today = {"AAPL": _signal(94.0, signal=SignalType.NEUTRAL)}

    _process_exits(portfolio, trades, open_meta, signals_today, current_date=date(2022, 1, 4))

    assert "AAPL" not in open_meta
    assert trades[-1].action == "SELL" and "Zarar-kes" in trades[-1].reason


def test_process_exits_takes_partial_profit_then_closes_remainder_later():
    portfolio = PaperPortfolio(starting_cash=10_000.0)
    portfolio.buy("AAPL", 10.0, 100.0)
    trades: list[BacktestTrade] = []
    open_meta = {"AAPL": _OpenPosition(stop_loss=95.0, take_profit=110.0, take_profit_2=120.0)}

    _process_exits(portfolio, trades, open_meta, {"AAPL": _signal(111.0)}, current_date=date(2022, 1, 4))

    assert "AAPL" in open_meta  # still open -- only half closed
    assert open_meta["AAPL"].partial_exit_done is True
    assert open_meta["AAPL"].take_profit == pytest.approx(120.0)
    assert trades[-1].action == "SELL" and "Kısmi" in trades[-1].reason
    remaining_qty = next(p.quantity for p in portfolio.snapshot().positions if p.symbol == "AAPL")
    assert remaining_qty == pytest.approx(5.0)

    _process_exits(portfolio, trades, open_meta, {"AAPL": _signal(121.0)}, current_date=date(2022, 1, 5))

    assert "AAPL" not in open_meta
    assert trades[-1].action == "SELL" and "Kâr-al" in trades[-1].reason


# -- end-to-end orchestration (network calls monkeypatched out) ----------------------

def test_run_backtest_with_no_historical_data_returns_empty_result(monkeypatch):
    monkeypatch.setattr(backtest_engine, "fetch_historical_series", lambda *a, **k: {})
    monkeypatch.setattr(backtest_engine, "fetch_single_series", lambda *a, **k: [])

    result = run_backtest(
        market="test", symbols=["AAPL"], ticker_suffix="", benchmark_symbol="^GSPC",
        vix_available=False, initial_cash=10_000.0, years=3,
    )

    assert result.symbols_included == 0
    assert result.symbols_skipped == 1
    assert result.trade_count == 0
    assert result.final_equity == 10_000.0


def test_run_backtest_end_to_end_on_a_realistic_uptrend(monkeypatch):
    bars = _realistic_uptrend_bars(days=300, base_volume=2_000_000.0)
    monkeypatch.setattr(backtest_engine, "fetch_historical_series", lambda *a, **k: {"AAPL": bars})
    monkeypatch.setattr(backtest_engine, "fetch_single_series", lambda *a, **k: [])

    result = run_backtest(
        market="test", symbols=["AAPL"], ticker_suffix="", benchmark_symbol=None,
        vix_available=False, initial_cash=10_000.0, years=3,
    )

    assert result.symbols_included == 1
    assert len(result.equity_curve) == len(bars)
    assert result.equity_curve[0].date == bars[0].timestamp
    assert result.equity_curve[-1].date == bars[-1].timestamp
    assert result.start_date == bars[0].timestamp
    assert result.end_date == bars[-1].timestamp
    # A real, noisy-but-net-upward series over 300 days should trigger at
    # least one buy through the actual scoring engine (not a hand-crafted
    # signal) -- this is the one test proving the whole pipeline (historical
    # bars -> ScannerEngine -> SignalEngine -> entry/exit logic -> portfolio)
    # is wired together correctly end to end.
    assert any(t.action == "BUY" for t in result.trades)
    # Every open position must have been liquidated by the final day -- no
    # position should silently vanish from the trade log without a matching close.
    assert portfolio_is_fully_closed(result)


def portfolio_is_fully_closed(result) -> bool:
    open_qty: dict[str, float] = {}
    for t in result.trades:
        if t.action == "BUY":
            open_qty[t.symbol] = open_qty.get(t.symbol, 0.0) + t.quantity
        else:
            open_qty[t.symbol] = open_qty.get(t.symbol, 0.0) - t.quantity
    return all(abs(q) < 1e-6 for q in open_qty.values())


def test_gap_day_produces_no_trade_for_the_affected_symbol(monkeypatch):
    # AAPL trades every day (keeps this date on the all_dates axis); MSFT is
    # missing exactly one day's bar, simulating a single-symbol data hiccup
    # rather than a universal exchange holiday (which would already be
    # absent from every symbol's bars, never reaching this code path).
    # Before the fix, compute_indicators() would still return MSFT's stale,
    # unchanged snapshot from the day before -- evaluating that again could
    # produce a trade "on" a day MSFT never actually had a price for.
    bars_a = _realistic_uptrend_bars(days=200, base_volume=2_000_000.0, seed=42)
    bars_b = _realistic_uptrend_bars(days=200, base_volume=2_000_000.0, seed=43)
    gap_date = bars_b[150].timestamp.date()
    bars_b_with_gap = [b for b in bars_b if b.timestamp.date() != gap_date]

    monkeypatch.setattr(
        backtest_engine, "fetch_historical_series",
        lambda *a, **k: {"AAPL": bars_a, "MSFT": bars_b_with_gap},
    )
    monkeypatch.setattr(backtest_engine, "fetch_single_series", lambda *a, **k: [])

    result = run_backtest(
        market="test", symbols=["AAPL", "MSFT"], ticker_suffix="", benchmark_symbol=None,
        vix_available=False, initial_cash=10_000.0, years=3,
    )

    assert not any(t.symbol == "MSFT" and t.date.date() == gap_date for t in result.trades)


def test_run_backtest_liquidates_any_position_still_open_at_the_end(monkeypatch):
    bars = _realistic_uptrend_bars(days=260, base_volume=2_000_000.0)
    monkeypatch.setattr(backtest_engine, "fetch_historical_series", lambda *a, **k: {"AAPL": bars})
    monkeypatch.setattr(backtest_engine, "fetch_single_series", lambda *a, **k: [])

    result = run_backtest(
        market="test", symbols=["AAPL"], ticker_suffix="", benchmark_symbol=None,
        vix_available=False, initial_cash=10_000.0, years=3,
    )

    assert portfolio_is_fully_closed(result)
