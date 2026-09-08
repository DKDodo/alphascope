"""Combines category scores into a 0-100 Opportunity Score and classifies it."""
from __future__ import annotations

from datetime import datetime, timezone

from app.risk.risk_engine import RiskAnalysis, RiskEngine
from app.scanner.scanner_engine import IndicatorSnapshot
from app.signals import scoring
from app.signals.dip_detector import detect_dip_opportunity
from app.signals.models import CategoryScores, SignalResult, SignalType

_THRESHOLDS: list[tuple[int, SignalType]] = [
    (85, SignalType.STRONG_BUY_SETUP),
    (75, SignalType.BUY_SETUP),
    (65, SignalType.WATCH),
    (40, SignalType.NEUTRAL),
    (0, SignalType.AVOID),
]


def classify_score(score: int) -> SignalType:
    for threshold, signal in _THRESHOLDS:
        if score >= threshold:
            return signal
    return SignalType.AVOID


class SignalEngine:
    def __init__(self, risk_engine: RiskEngine | None = None) -> None:
        self._risk_engine = risk_engine or RiskEngine()

    def evaluate(
        self, ind: IndicatorSnapshot, daily_trend_up: bool | None = None
    ) -> SignalResult | None:
        risk_analysis: RiskAnalysis | None = None
        if ind.atr14 is not None and ind.atr14 > 0:
            resistance_price = ind.bollinger.upper if ind.bollinger is not None else None
            risk_analysis = self._risk_engine.analyze(
                entry_price=ind.price, atr=ind.atr14, resistance_price=resistance_price
            )

        trend_score, trend_reasons = scoring.score_trend(ind)
        momentum_score, momentum_reasons = scoring.score_momentum(ind)
        volume_score, volume_reasons = scoring.score_volume(ind)
        price_action_score, price_action_reasons = scoring.score_price_action(ind)
        risk_reward_score, risk_reward_reasons = scoring.score_risk_reward(risk_analysis)

        category_scores = CategoryScores(
            trend=trend_score,
            momentum=momentum_score,
            volume=volume_score,
            price_action=price_action_score,
            risk_reward=risk_reward_score,
        )
        total_score = category_scores.total
        signal = classify_score(total_score)

        reasons = [
            *trend_reasons,
            *momentum_reasons,
            *volume_reasons,
            *price_action_reasons,
            *risk_reward_reasons,
        ]

        risk_level = risk_analysis.risk_level if risk_analysis else _fallback_risk_level(total_score)
        buy_zone_low, buy_zone_high = _compute_buy_zone(ind)

        return SignalResult(
            symbol=ind.symbol,
            price=ind.price,
            score=total_score,
            signal=signal,
            reasons=reasons,
            risk_level=risk_level,
            category_scores=category_scores,
            risk_analysis=risk_analysis,
            buy_zone_low=buy_zone_low,
            buy_zone_high=buy_zone_high,
            bars_available=ind.bars_available,
            data_age_seconds=_compute_data_age(ind),
            dip_opportunity=detect_dip_opportunity(ind),
            daily_trend_up=daily_trend_up,
        )


def _compute_buy_zone(ind: IndicatorSnapshot) -> tuple[float | None, float | None]:
    """A rough 'attractive pullback' reference band: from the 20-bar
    Bollinger middle band down to one ATR below it. This describes where a
    pullback would re-enter a statistically normal range for this symbol —
    it is not a prediction the price will get there, just a reference zone
    derived from current volatility and the moving average."""
    if ind.bollinger is None or ind.atr14 is None or ind.atr14 <= 0:
        return None, None
    high = ind.bollinger.middle
    low = ind.bollinger.middle - ind.atr14
    return round(low, 4), round(high, 4)


def _fallback_risk_level(score: int):
    from app.risk.risk_engine import RiskLevel

    return RiskLevel.MEDIUM


def _compute_data_age(ind: IndicatorSnapshot) -> float | None:
    if ind.last_bar_time is None:
        return None
    bar_time = ind.last_bar_time
    if bar_time.tzinfo is None:
        bar_time = bar_time.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - bar_time).total_seconds()
    return max(0.0, age)
