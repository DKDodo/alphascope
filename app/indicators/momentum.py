"""RSI and MACD."""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from app.indicators.moving_average import ema_series


def rsi(values: Sequence[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    arr = np.asarray(values, dtype=float)
    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


class MacdResult:
    __slots__ = ("macd_line", "signal_line", "histogram")

    def __init__(self, macd_line: float, signal_line: float, histogram: float) -> None:
        self.macd_line = macd_line
        self.signal_line = signal_line
        self.histogram = histogram


def macd(
    values: Sequence[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> MacdResult | None:
    if len(values) < slow_period + signal_period:
        return None

    fast_series = ema_series(values, fast_period)
    slow_series = ema_series(values, slow_period)
    if fast_series is None or slow_series is None:
        return None

    offset = len(fast_series) - len(slow_series)
    macd_series = [f - s for f, s in zip(fast_series[offset:], slow_series)]

    signal_series = ema_series(macd_series, signal_period)
    if signal_series is None:
        return None

    macd_line = macd_series[-1]
    signal_line = signal_series[-1]
    return MacdResult(
        macd_line=macd_line,
        signal_line=signal_line,
        histogram=macd_line - signal_line,
    )
