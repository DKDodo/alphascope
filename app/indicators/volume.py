"""Volume-based indicators: ratio to average, and rolling VWAP."""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def volume_ratio(current_volume: float, volumes: Sequence[float], lookback: int = 20) -> float | None:
    history = volumes[-lookback:] if len(volumes) >= lookback else volumes
    if not history:
        return None
    avg = float(np.mean(history))
    if avg == 0:
        return None
    return current_volume / avg


def vwap(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float],
) -> float | None:
    if not closes or not volumes:
        return None
    highs_arr = np.asarray(highs, dtype=float)
    lows_arr = np.asarray(lows, dtype=float)
    closes_arr = np.asarray(closes, dtype=float)
    volumes_arr = np.asarray(volumes, dtype=float)

    typical_price = (highs_arr + lows_arr + closes_arr) / 3.0
    total_volume = float(np.sum(volumes_arr))
    if total_volume == 0:
        return None
    return float(np.sum(typical_price * volumes_arr) / total_volume)


def momentum(values: Sequence[float], period: int = 10) -> float | None:
    """Simple rate-of-change momentum: percent change over `period` bars."""
    if len(values) < period + 1:
        return None
    start = values[-(period + 1)]
    end = values[-1]
    if start == 0:
        return None
    return (end - start) / start * 100.0
