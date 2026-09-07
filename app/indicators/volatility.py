"""ATR and Bollinger Bands."""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> float | None:
    if len(closes) < period + 1:
        return None

    highs_arr = np.asarray(highs, dtype=float)
    lows_arr = np.asarray(lows, dtype=float)
    closes_arr = np.asarray(closes, dtype=float)

    prev_closes = closes_arr[:-1]
    high_low = highs_arr[1:] - lows_arr[1:]
    high_prev_close = np.abs(highs_arr[1:] - prev_closes)
    low_prev_close = np.abs(lows_arr[1:] - prev_closes)

    true_ranges = np.maximum(high_low, np.maximum(high_prev_close, low_prev_close))
    if len(true_ranges) < period:
        return None

    # Wilder's smoothing.
    avg = np.mean(true_ranges[:period])
    for i in range(period, len(true_ranges)):
        avg = (avg * (period - 1) + true_ranges[i]) / period
    return float(avg)


class BollingerBands:
    __slots__ = ("upper", "middle", "lower")

    def __init__(self, upper: float, middle: float, lower: float) -> None:
        self.upper = upper
        self.middle = middle
        self.lower = lower


def bollinger_bands(
    values: Sequence[float], period: int = 20, std_dev: float = 2.0
) -> BollingerBands | None:
    if len(values) < period:
        return None
    window = np.asarray(values[-period:], dtype=float)
    middle = float(np.mean(window))
    std = float(np.std(window))
    return BollingerBands(
        upper=middle + std_dev * std,
        middle=middle,
        lower=middle - std_dev * std,
    )
