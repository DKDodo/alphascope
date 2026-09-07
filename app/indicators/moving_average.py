"""Simple and exponential moving averages."""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def sma(values: Sequence[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return float(np.mean(values[-period:]))


def ema_series(values: Sequence[float], period: int) -> list[float] | None:
    """Full EMA series over `values`, or None if there isn't enough history."""
    if len(values) < period:
        return None
    arr = np.asarray(values, dtype=float)
    alpha = 2.0 / (period + 1)
    result = np.empty_like(arr)
    result[0] = arr[0]
    for i in range(1, len(arr)):
        result[i] = alpha * arr[i] + (1 - alpha) * result[i - 1]
    return result.tolist()


def ema(values: Sequence[float], period: int) -> float | None:
    """Latest EMA value, seeded from the full available history."""
    series = ema_series(values, period)
    return series[-1] if series else None
