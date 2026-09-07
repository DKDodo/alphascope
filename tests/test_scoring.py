from __future__ import annotations

import pytest

from app.risk.risk_engine import RiskAnalysis, RiskEngine, RiskLevel
from app.scanner.scanner_engine import IndicatorSnapshot
from app.signals import scoring
from app.signals.signal_engine import SignalEngine, classify_score
from app.signals.models import SignalType


def _snapshot(**overrides) -> IndicatorSnapshot:
    defaults = dict(
        symbol="TEST",
        price=100.0,
        ema9=None,
        ema20=None,
        ema50=None,
        ema200=None,
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


@pytest.mark.parametrize(
    "score,expected",
    [
        (100, SignalType.STRONG_BUY_SETUP),
        (85, SignalType.STRONG_BUY_SETUP),
        (84, SignalType.BUY_SETUP),
        (75, SignalType.BUY_SETUP),
        (74, SignalType.WATCH),
        (65, SignalType.WATCH),
        (64, SignalType.NEUTRAL),
        (40, SignalType.NEUTRAL),
        (39, SignalType.AVOID),
        (0, SignalType.AVOID),
    ],
)
def test_signal_classification_boundaries(score, expected):
    assert classify_score(score) == expected


def test_category_scores_never_exceed_cap():
    ind = _snapshot(ema9=110, ema20=100, ema50=90, ema200=80, rsi14=50, momentum_roc=10)
    trend_score, _ = scoring.score_trend(ind)
    momentum_score, _ = scoring.score_momentum(ind)
    assert 0 <= trend_score <= 20
    assert 0 <= momentum_score <= 20


def test_trend_score_zero_when_no_indicators_available():
    ind = _snapshot()
    score, reasons = scoring.score_trend(ind)
    assert score == 0
    assert reasons == []


def test_volume_score_scales_with_ratio():
    low = scoring.score_volume(_snapshot(volume_ratio=1.2))[0]
    mid = scoring.score_volume(_snapshot(volume_ratio=1.6))[0]
    high = scoring.score_volume(_snapshot(volume_ratio=2.5))[0]
    assert low < mid < high
    assert high == 20


def test_risk_reward_score_scales_with_ratio():
    def _risk(ratio: float) -> RiskAnalysis:
        return RiskAnalysis(
            entry_price=100.0,
            stop_loss=95.0,
            take_profit_1=100.0 + ratio * 5.0,
            take_profit_2=110.0,
            atr=5.0,
            risk_per_share=5.0,
            reward_per_share_tp1=ratio * 5.0,
            risk_reward_ratio=ratio,
            risk_level=RiskLevel.MEDIUM,
        )

    assert scoring.score_risk_reward(None) == (0, [])
    assert scoring.score_risk_reward(_risk(3.5))[0] == 20
    assert scoring.score_risk_reward(_risk(0.5))[0] == 0


def test_risk_reward_negative_reason_when_ratio_weak():
    risk = RiskAnalysis(
        entry_price=100.0, stop_loss=95.0, take_profit_1=102.0, take_profit_2=105.0,
        atr=5.0, risk_per_share=5.0, reward_per_share_tp1=2.0, risk_reward_ratio=0.4,
        risk_level=RiskLevel.MEDIUM,
    )
    score, reasons = scoring.score_risk_reward(risk)
    assert score == 0
    assert len(reasons) == 1
    assert reasons[0].positive is False


def test_trend_score_flags_bearish_emas_with_negative_reasons():
    ind = _snapshot(ema9=90, ema20=100, ema50=110, ema200=120)
    score, reasons = scoring.score_trend(ind)
    assert score == 0
    assert len(reasons) == 3
    assert all(r.positive is False for r in reasons)


def test_momentum_score_flags_overbought_rsi():
    ind = _snapshot(rsi14=78.0)
    score, reasons = scoring.score_momentum(ind)
    assert score == 0
    assert any("aşırı alım" in r.text and r.positive is False for r in reasons)


def test_volume_score_flags_low_volume():
    score, reasons = scoring.score_volume(_snapshot(volume_ratio=0.6))
    assert score == 0
    assert reasons[0].positive is False


def test_price_action_flags_price_below_vwap():
    from app.indicators.volatility import BollingerBands

    ind = _snapshot(
        price=95.0,
        bollinger=BollingerBands(upper=110.0, middle=100.0, lower=90.0),
        vwap=98.0,
    )
    score, reasons = scoring.score_price_action(ind)
    assert any("VWAP altında" in r.text and r.positive is False for r in reasons)


def test_signal_engine_computes_buy_zone_below_bollinger_middle():
    from app.indicators.volatility import BollingerBands

    ind = _snapshot(price=105.0, atr14=4.0, bollinger=BollingerBands(upper=112.0, middle=100.0, lower=88.0))
    engine = SignalEngine(risk_engine=RiskEngine())
    result = engine.evaluate(ind)

    assert result is not None
    assert result.buy_zone_high == 100.0
    assert result.buy_zone_low == 96.0  # bollinger middle - ATR
    assert result.buy_zone_low < result.buy_zone_high


def test_signal_engine_buy_zone_none_without_enough_data():
    ind = _snapshot(price=105.0)
    engine = SignalEngine(risk_engine=RiskEngine())
    result = engine.evaluate(ind)

    assert result is not None
    assert result.buy_zone_low is None
    assert result.buy_zone_high is None
