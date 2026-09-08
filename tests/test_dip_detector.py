from __future__ import annotations

from app.indicators.volatility import BollingerBands
from app.scanner.scanner_engine import IndicatorSnapshot
from app.signals.dip_detector import detect_dip_opportunity
from app.signals.models import DipConfidence


def _snapshot(**overrides) -> IndicatorSnapshot:
    defaults = dict(
        symbol="TEST",
        price=100.0,
        ema9=None, ema20=None, ema50=None, ema200=None,
        rsi14=None,
        macd=None,
        atr14=None,
        bollinger=None,
        vwap=None,
        volume_ratio=None,
        momentum_roc=None,
        bars_available=250,
    )
    defaults.update(overrides)
    return IndicatorSnapshot(**defaults)


def test_returns_none_without_enough_data():
    assert detect_dip_opportunity(_snapshot(rsi14=20.0)) is None
    assert detect_dip_opportunity(
        _snapshot(rsi14=20.0, bollinger=BollingerBands(upper=110.0, middle=100.0, lower=95.0))
    ) is None


def test_returns_none_when_oversold_but_far_from_support():
    ind = _snapshot(
        price=105.0,  # well above the lower band
        rsi14=25.0,
        bollinger=BollingerBands(upper=115.0, middle=105.0, lower=95.0),
        volume_ratio=1.5,
    )
    assert detect_dip_opportunity(ind) is None


def test_returns_none_when_near_support_but_not_oversold():
    ind = _snapshot(
        price=95.5,
        rsi14=50.0,  # not oversold
        bollinger=BollingerBands(upper=115.0, middle=105.0, lower=95.0),
        volume_ratio=1.5,
    )
    assert detect_dip_opportunity(ind) is None


def test_strong_confidence_with_high_volume():
    ind = _snapshot(
        price=94.0,
        rsi14=22.0,
        bollinger=BollingerBands(upper=115.0, middle=105.0, lower=95.0),
        volume_ratio=2.5,
    )
    result = detect_dip_opportunity(ind)

    assert result is not None
    assert result.confidence == DipConfidence.STRONG
    assert all(r.positive for r in result.reasons)


def test_medium_confidence_with_moderate_volume():
    ind = _snapshot(
        price=94.0,
        rsi14=22.0,
        bollinger=BollingerBands(upper=115.0, middle=105.0, lower=95.0),
        volume_ratio=1.5,
    )
    result = detect_dip_opportunity(ind)

    assert result is not None
    assert result.confidence == DipConfidence.MEDIUM


def test_weak_confidence_with_low_volume_has_a_negative_reason():
    ind = _snapshot(
        price=94.0,
        rsi14=22.0,
        bollinger=BollingerBands(upper=115.0, middle=105.0, lower=95.0),
        volume_ratio=0.8,
    )
    result = detect_dip_opportunity(ind)

    assert result is not None
    assert result.confidence == DipConfidence.WEAK
    assert any(r.positive is False for r in result.reasons)


def test_price_exactly_at_lower_band_counts_as_near_support():
    ind = _snapshot(
        price=95.0,  # exactly at the lower band
        rsi14=25.0,
        bollinger=BollingerBands(upper=115.0, middle=105.0, lower=95.0),
        volume_ratio=1.3,
    )
    assert detect_dip_opportunity(ind) is not None
