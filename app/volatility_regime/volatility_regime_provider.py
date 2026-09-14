"""Computes a market's self-contained realized-volatility risk multiplier
from its own benchmark index, instead of VIX -- see VolatilityRegime's
docstring for why. multiplier_series_by_date() is the one piece of actual
math, shared by this live poller and the backtest replay
(app/backtest/backtest_engine.py imports it directly) so the two can never
quietly diverge; fetch_volatility_regime() is just this module's own
yfinance plumbing around it.

Calibrated against real history, not guessed: a 20-day realized-vol reading
correlated 0.60 with real VIX on Global's own 3y history (checked before
building this at all -- if it hadn't tracked real VIX at all there, there'd
be no basis for trusting it on BIST, which has no VIX to check against).
The 80th/95th percentile cutoffs land almost exactly on real VIX's own
20/30 elevated/high levels on that same data (VIX averaged 21.1 on days
above the computed 80th percentile, 26.5 above the 95th, vs 16.5 otherwise).
"""
from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timezone
from typing import Any

import numpy as np

from app.core.logging import get_logger
from app.volatility_regime.models import VolatilityRegime

logger = get_logger(__name__)

LOOKBACK_PERIOD = "3y"  # matches the backtest's own default `years` -- same data, same conclusions
REALIZED_VOL_WINDOW_DAYS = 20  # matches VIX's own ~1-month implied-vol horizon
MIN_WARMUP_DAYS = 60  # don't classify a percentile off too thin a sample
ELEVATED_PERCENTILE = 80.0
HIGH_PERCENTILE = 95.0
# Same values VIX-based derating already used (VIX_ELEVATED_THRESHOLD's 0.5x
# / VIX_HIGH_THRESHOLD's 0.25x in autotrader_service.py) -- this changes the
# SIGNAL (self-relative percentile instead of an absolute VIX level), not
# the derating policy itself.
ELEVATED_MULTIPLIER = 0.5
HIGH_MULTIPLIER = 0.25


def multiplier_series_by_date(dates: list[date_type], closes: list[float]) -> dict[date_type, float]:
    """The full by-date risk-multiplier series for a benchmark's chronological
    closes -- what the backtest needs (one value per replayed day, each
    computed only from bars up to and including that day, never past it, so
    it can't see the future). The live poller wants only the most recent
    entry (fetch_volatility_regime() below calls this and reads the tail),
    which is why this returns the whole dict rather than "just the latest"
    -- one function, two ways of reading it, instead of two implementations
    that could drift apart.
    """
    if len(dates) < REALIZED_VOL_WINDOW_DAYS + MIN_WARMUP_DAYS:
        return {}

    closes_arr = np.asarray(closes, dtype=float)
    returns = np.diff(closes_arr) / closes_arr[:-1]

    # realized_vol[i] uses returns[i-WINDOW:i] -- i.e. it's "as of" dates[i]
    # (the return INTO day i is the last one included), never a future bar.
    realized_vol: list[float | None] = [None] * len(dates)
    for i in range(REALIZED_VOL_WINDOW_DAYS, len(dates)):
        window = returns[i - REALIZED_VOL_WINDOW_DAYS : i]
        realized_vol[i] = float(np.std(window, ddof=1)) * (252 ** 0.5) * 100

    result: dict[date_type, float] = {}
    for i, vol in enumerate(realized_vol):
        if vol is None:
            continue
        history = [v for v in realized_vol[:i] if v is not None]  # strictly prior days only
        if len(history) < MIN_WARMUP_DAYS:
            continue
        p95 = float(np.percentile(history, HIGH_PERCENTILE))
        p80 = float(np.percentile(history, ELEVATED_PERCENTILE))
        if vol >= p95:
            result[dates[i]] = HIGH_MULTIPLIER
        elif vol >= p80:
            result[dates[i]] = ELEVATED_MULTIPLIER
        else:
            result[dates[i]] = 1.0
    return result


def _percentile_rank(history: list[float], latest: float) -> float:
    if not history:
        return 0.0
    return float((np.asarray(history) < latest).mean() * 100)


def fetch_volatility_regime(benchmark_symbol: str) -> VolatilityRegime | None:
    import yfinance as yf  # imported lazily, same as every other yfinance call site

    now = datetime.now(timezone.utc)
    try:
        # group_by="ticker": without it, a MultiIndex download's levels come
        # back (field, ticker) -- e.g. ("Close", "XU100.IS") -- instead of
        # the (ticker, field) shape _parse_download() (and every other
        # yfinance call site in this codebase) expects. Verified live: a
        # bare yf.download(symbol, ...) with no group_by silently returned
        # that other orientation, so data[benchmark_symbol] raised KeyError
        # on every single poll (caught below, but every cycle came back empty).
        data = yf.download(benchmark_symbol, period=LOOKBACK_PERIOD, interval="1d", group_by="ticker", progress=False)
    except Exception:  # noqa: BLE001 - a bad Yahoo response must not crash the poll cycle
        logger.exception("volatility regime download failed for %s", benchmark_symbol)
        return None
    return _parse_download(benchmark_symbol, data, now)


def _parse_download(benchmark_symbol: str, data: Any, now: datetime) -> VolatilityRegime | None:
    import pandas as pd

    if data is None or data.empty:
        return None
    # A single-ticker yf.download() with no group_by has been seen to come
    # back MultiIndex-columned anyway on some yfinance versions/hosts --
    # len(tickers) > 1 alone was already proven unreliable as the signal
    # for this (app/backtest/historical_data.py, app/daily_trend/), so it's
    # not repeated here either.
    is_multi_indexed = isinstance(data.columns, pd.MultiIndex)
    try:
        frame = data[benchmark_symbol] if is_multi_indexed else data
        frame = frame.dropna(how="all")
        close_series = frame["Close"].dropna()
        closes = close_series.tolist()
        dates = [ts.date() for ts in close_series.index]
    except (KeyError, IndexError):
        logger.warning("volatility regime parse failed for %s", benchmark_symbol)
        return None
    if not closes:
        return None

    by_date = multiplier_series_by_date(dates, closes)
    if not by_date:
        return VolatilityRegime(benchmark_symbol=benchmark_symbol, as_of=now)  # not enough history yet

    latest_date = dates[-1]
    multiplier = by_date.get(latest_date, 1.0)

    # realized_vol_pct/percentile_rank are display-only (see models.py) --
    # recomputed here straightforwardly rather than threading them out of
    # multiplier_series_by_date's loop, since this only runs once per poll
    # cycle (every few hours), not per backtest day.
    closes_arr = np.asarray(closes, dtype=float)
    returns = np.diff(closes_arr) / closes_arr[:-1]
    if len(returns) < REALIZED_VOL_WINDOW_DAYS:
        return VolatilityRegime(benchmark_symbol=benchmark_symbol, risk_multiplier=multiplier, as_of=now)
    latest_vol = float(np.std(returns[-REALIZED_VOL_WINDOW_DAYS:], ddof=1)) * (252 ** 0.5) * 100
    history_vol = [
        float(np.std(returns[i - REALIZED_VOL_WINDOW_DAYS : i], ddof=1)) * (252 ** 0.5) * 100
        for i in range(REALIZED_VOL_WINDOW_DAYS, len(returns))
    ]
    rank = _percentile_rank(history_vol[:-1], latest_vol) if len(history_vol) > 1 else None

    return VolatilityRegime(
        benchmark_symbol=benchmark_symbol,
        realized_vol_pct=round(latest_vol, 2),
        percentile_rank=round(rank, 1) if rank is not None else None,
        risk_multiplier=multiplier,
        as_of=now,
    )
