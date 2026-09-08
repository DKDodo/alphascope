"""End-to-end SignalEngine.evaluate() scenarios (as opposed to test_scoring.py's
per-category unit tests) — positive trend, negative trend, sideways market,
missing data, and malformed/extreme data, plus the data-staleness check."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.indicators.momentum import MacdResult
from app.indicators.volatility import BollingerBands
from app.risk.risk_engine import RiskEngine
from app.scanner.scanner_engine import IndicatorSnapshot
from app.signals.models import DipConfidence, SignalType
from app.signals.signal_engine import SignalEngine


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
        last_bar_time=None,
    )
    defaults.update(overrides)
    return IndicatorSnapshot(**defaults)


def _engine() -> SignalEngine:
    return SignalEngine(risk_engine=RiskEngine())


def test_positive_trend_scenario_scores_high_and_all_reasons_favorable():
    ind = _snapshot(
        price=116.0,
        ema9=112.0, ema20=108.0, ema50=104.0, ema200=95.0,
        rsi14=58.0,
        macd=MacdResult(macd_line=1.2, signal_line=0.8, histogram=0.4),
        momentum_roc=3.5,
        volume_ratio=2.2,
        bollinger=BollingerBands(upper=115.0, middle=110.0, lower=105.0),
        vwap=113.0,
        atr14=3.0,
    )
    result = _engine().evaluate(ind)

    assert result is not None
    assert result.score >= 75
    assert result.signal in (SignalType.STRONG_BUY_SETUP, SignalType.BUY_SETUP)
    assert len(result.reasons) > 0
    assert all(r.positive for r in result.reasons)


def test_negative_trend_scenario_scores_low_and_all_reasons_unfavorable():
    ind = _snapshot(
        price=94.0,
        ema9=95.0, ema20=100.0, ema50=105.0, ema200=110.0,
        rsi14=25.0,
        macd=MacdResult(macd_line=-1.0, signal_line=-0.5, histogram=-0.5),
        momentum_roc=-4.0,
        volume_ratio=0.7,
        # Resistance close to price (not far away like a healthy uptrend
        # would have) -- keeps risk/reward weak too, since RiskEngine anchors
        # TP1 to this level regardless of trend direction.
        bollinger=BollingerBands(upper=97.0, middle=92.0, lower=87.0),
        vwap=97.0,
        atr14=3.0,
    )
    result = _engine().evaluate(ind)

    assert result is not None
    assert result.score <= 20
    assert result.signal == SignalType.AVOID
    assert len(result.reasons) > 0
    assert all(r.positive is False for r in result.reasons)
    assert result.dip_opportunity is None  # price isn't near the lower band in this scenario


def test_dip_opportunity_can_coexist_with_a_low_trend_score():
    # Trend/momentum are still bearish (AVOID by trend rules), but price
    # sits right at the lower Bollinger band with RSI oversold and some
    # volume behind it -- a textbook mean-reversion dip candidate. The two
    # reads deliberately disagree here, and that's the point: the trend
    # Opportunity Score must not swallow or hide the separate dip read.
    ind = _snapshot(
        price=95.0,
        ema9=95.0, ema20=100.0, ema50=105.0, ema200=110.0,
        rsi14=22.0,
        macd=MacdResult(macd_line=-1.0, signal_line=-0.5, histogram=-0.5),
        momentum_roc=-4.0,
        volume_ratio=1.6,
        bollinger=BollingerBands(upper=105.0, middle=100.0, lower=95.0),
        vwap=97.0,
        atr14=3.0,
    )
    result = _engine().evaluate(ind)

    assert result is not None
    assert result.signal == SignalType.AVOID
    assert result.dip_opportunity is not None
    assert result.dip_opportunity.confidence == DipConfidence.MEDIUM


def test_sideways_market_scenario_scores_mid_range():
    ind = _snapshot(
        price=100.0,
        ema9=100.2, ema20=100.0, ema50=99.9, ema200=100.1,
        rsi14=50.0,
        macd=MacdResult(macd_line=0.05, signal_line=0.04, histogram=0.01),
        momentum_roc=0.1,
        volume_ratio=1.1,
        bollinger=BollingerBands(upper=102.0, middle=100.0, lower=98.0),
        vwap=100.0,
        atr14=1.0,
    )
    result = _engine().evaluate(ind)

    assert result is not None
    # A flat/mixed market shouldn't read as a strong conviction in either direction.
    assert result.signal not in (SignalType.STRONG_BUY_SETUP,)
    assert 0 < result.score < 85


def test_missing_data_scenario_does_not_crash_and_scores_zero():
    ind = _snapshot(price=50.0, bars_available=3)  # everything else defaults to None
    result = _engine().evaluate(ind)

    assert result is not None
    assert result.score == 0
    assert result.signal == SignalType.AVOID
    assert result.bars_available == 3
    assert result.risk_analysis is None


def test_malformed_extreme_data_does_not_crash_and_stays_in_bounds():
    ind = _snapshot(
        price=0.0001,
        ema9=1e9, ema20=1.0, ema50=-5.0, ema200=0.0,
        rsi14=150.0,  # out of the normal 0-100 range
        macd=MacdResult(macd_line=float("inf"), signal_line=0.0, histogram=1.0),
        momentum_roc=-99999.0,
        volume_ratio=1e6,
        bollinger=BollingerBands(upper=1.0, middle=0.5, lower=0.0),
        vwap=0.0,
        atr14=1e9,
    )
    result = _engine().evaluate(ind)

    assert result is not None
    assert 0 <= result.score <= 100
    for category_score in (
        result.category_scores.trend,
        result.category_scores.momentum,
        result.category_scores.volume,
        result.category_scores.price_action,
        result.category_scores.risk_reward,
    ):
        assert 0 <= category_score <= 20


def test_data_age_is_none_without_a_last_bar_time():
    ind = _snapshot(price=100.0, last_bar_time=None)
    result = _engine().evaluate(ind)

    assert result.data_age_seconds is None


def test_data_age_reflects_how_old_the_last_bar_is():
    old_bar_time = datetime.now(timezone.utc) - timedelta(minutes=45)
    ind = _snapshot(price=100.0, last_bar_time=old_bar_time)
    result = _engine().evaluate(ind)

    assert result.data_age_seconds is not None
    assert 2600 <= result.data_age_seconds <= 2800  # ~45 minutes, allowing test runtime slack


def test_data_age_handles_naive_timestamps_without_crashing():
    # SQLite drops tzinfo on round-trip (see app/main.py's _as_utc) -- a
    # naive timestamp reaching here must not raise, and must still be
    # treated as UTC rather than silently producing a huge/negative age.
    naive_bar_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)
    ind = _snapshot(price=100.0, last_bar_time=naive_bar_time)
    result = _engine().evaluate(ind)

    assert result.data_age_seconds is not None
    assert 500 <= result.data_age_seconds <= 700  # ~10 minutes
