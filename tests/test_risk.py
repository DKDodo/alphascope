from __future__ import annotations

import pytest

from app.core.exceptions import RiskCalculationError
from app.risk.position_sizing import calculate_position_size
from app.risk.risk_engine import RiskEngine, RiskLevel


def test_risk_engine_stop_below_entry_for_long_bias():
    engine = RiskEngine()
    result = engine.analyze(entry_price=100.0, atr=2.0)
    assert result.stop_loss < result.entry_price
    assert result.take_profit_1 > result.entry_price
    assert result.take_profit_2 > result.take_profit_1


def test_risk_engine_risk_reward_ratio_positive():
    engine = RiskEngine()
    result = engine.analyze(entry_price=100.0, atr=2.0)
    assert result.risk_reward_ratio > 0


def test_risk_engine_classifies_high_volatility():
    engine = RiskEngine()
    result = engine.analyze(entry_price=100.0, atr=5.0)  # 5% ATR
    assert result.risk_level == RiskLevel.HIGH


def test_risk_engine_classifies_low_volatility():
    engine = RiskEngine()
    result = engine.analyze(entry_price=100.0, atr=0.5)  # 0.5% ATR
    assert result.risk_level == RiskLevel.LOW


def test_risk_engine_rejects_non_positive_atr():
    engine = RiskEngine()
    with pytest.raises(RiskCalculationError):
        engine.analyze(entry_price=100.0, atr=0.0)


def test_risk_reward_ratio_varies_with_resistance_distance():
    # Without a resistance price, the ratio is a fixed ATR-multiple constant
    # (tp1_mult/stop_mult) regardless of symbol — this was the bug: it never
    # actually distinguished a good setup from a bad one.
    engine = RiskEngine()
    fallback = engine.analyze(entry_price=100.0, atr=2.0)

    near_resistance = engine.analyze(entry_price=100.0, atr=2.0, resistance_price=101.0)
    far_resistance = engine.analyze(entry_price=100.0, atr=2.0, resistance_price=120.0)

    assert near_resistance.risk_reward_ratio != far_resistance.risk_reward_ratio
    assert far_resistance.risk_reward_ratio > near_resistance.risk_reward_ratio
    assert far_resistance.take_profit_1 == 120.0
    # A resistance level miles above price shouldn't move the fallback ratio.
    assert fallback.risk_reward_ratio == round(2.0 / 1.5, 2)


def test_risk_reward_resistance_below_entry_falls_back_to_atr():
    engine = RiskEngine()
    fallback = engine.analyze(entry_price=100.0, atr=2.0)
    with_bad_resistance = engine.analyze(entry_price=100.0, atr=2.0, resistance_price=95.0)
    assert with_bad_resistance.take_profit_1 == fallback.take_profit_1


def test_risk_reward_resistance_too_close_uses_atr_floor():
    engine = RiskEngine()
    # Resistance sitting just above entry shouldn't produce a near-zero target.
    result = engine.analyze(entry_price=100.0, atr=2.0, resistance_price=100.1)
    assert result.take_profit_1 == 101.0  # entry + atr * 0.5 floor


def test_position_sizing_respects_risk_percent():
    size = calculate_position_size(
        account_balance=10_000.0, risk_percent=1.0, entry_price=50.0, stop_price=48.0
    )
    assert size.risk_amount == 100.0  # 1% of 10,000
    assert size.shares == 50.0  # 100 / (50 - 48)


def test_position_sizing_rejects_equal_entry_and_stop():
    with pytest.raises(RiskCalculationError):
        calculate_position_size(
            account_balance=10_000.0, risk_percent=1.0, entry_price=50.0, stop_price=50.0
        )


def test_position_sizing_rejects_invalid_risk_percent():
    with pytest.raises(RiskCalculationError):
        calculate_position_size(
            account_balance=10_000.0, risk_percent=0.0, entry_price=50.0, stop_price=48.0
        )
