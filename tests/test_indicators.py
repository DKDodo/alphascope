from __future__ import annotations

from app.indicators.momentum import macd, rsi
from app.indicators.moving_average import ema, sma
from app.indicators.volatility import atr, bollinger_bands
from app.indicators.volume import momentum, vwap, volume_ratio


def test_sma_basic():
    assert sma([1, 2, 3, 4, 5], 5) == 3.0


def test_sma_insufficient_data_returns_none():
    assert sma([1, 2], 5) is None


def test_ema_converges_toward_trending_data():
    rising = list(range(1, 51))
    value = ema(rising, 20)
    assert value is not None
    assert value > sma(rising, 20)  # EMA should weight recent (higher) values more


def test_rsi_all_gains_is_100():
    values = [float(i) for i in range(1, 30)]  # strictly increasing
    result = rsi(values, 14)
    assert result == 100.0


def test_rsi_all_losses_is_0():
    values = [float(i) for i in range(30, 1, -1)]  # strictly decreasing
    result = rsi(values, 14)
    assert result == 0.0


def test_rsi_insufficient_data_returns_none():
    assert rsi([1.0, 2.0], 14) is None


def test_macd_returns_none_with_insufficient_history():
    assert macd([1.0] * 10) is None


def test_macd_bullish_on_rising_series():
    values = [100 + i * 0.5 for i in range(60)]
    result = macd(values)
    assert result is not None
    assert result.macd_line > 0


def test_atr_insufficient_data_returns_none():
    assert atr([1, 2], [1, 2], [1, 2], 14) is None


def test_atr_positive_for_volatile_series():
    highs = [100 + i + 2 for i in range(20)]
    lows = [100 + i - 2 for i in range(20)]
    closes = [100 + i for i in range(20)]
    result = atr(highs, lows, closes, 14)
    assert result is not None
    assert result > 0


def test_bollinger_bands_ordering():
    values = [100, 101, 99, 102, 98, 103, 97, 104, 96, 105,
              100, 101, 99, 102, 98, 103, 97, 104, 96, 105]
    bands = bollinger_bands(values, 20, 2.0)
    assert bands is not None
    assert bands.lower < bands.middle < bands.upper


def test_volume_ratio_above_average():
    volumes = [100.0] * 20
    assert volume_ratio(300.0, volumes, lookback=20) == 3.0


def test_vwap_matches_typical_price_for_uniform_volume():
    highs = [10.0, 10.0]
    lows = [8.0, 8.0]
    closes = [9.0, 9.0]
    volumes = [100.0, 100.0]
    result = vwap(highs, lows, closes, volumes)
    assert result == 9.0


def test_momentum_positive_for_rising_series():
    values = [float(i) for i in range(1, 20)]
    result = momentum(values, period=10)
    assert result is not None
    assert result > 0
