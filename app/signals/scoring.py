"""Deterministic, rule-based per-category scoring (each capped 0-20).

Every function returns both score-supporting reasons (positive=True) and
factors working against the signal (positive=False) — an AVOID/NEUTRAL
result should be just as explainable as a BUY_SETUP one.
"""
from __future__ import annotations

from app.risk.risk_engine import RiskAnalysis
from app.scanner.scanner_engine import IndicatorSnapshot
from app.signals.models import Reason

MAX_CATEGORY_SCORE = 20


def score_trend(ind: IndicatorSnapshot) -> tuple[int, list[Reason]]:
    score = 0
    reasons: list[Reason] = []

    if ind.ema9 is not None and ind.ema20 is not None:
        if ind.ema9 > ind.ema20:
            score += 7
            reasons.append(Reason(text="EMA9, EMA20 üzerinde", positive=True))
        else:
            reasons.append(Reason(text="EMA9, EMA20'nin altında — kısa vadeli zayıflık", positive=False))

    if ind.ema20 is not None and ind.ema50 is not None:
        if ind.ema20 > ind.ema50:
            score += 7
            reasons.append(Reason(text="EMA20, EMA50 üzerinde", positive=True))
        else:
            reasons.append(Reason(text="EMA20, EMA50'nin altında — orta vadeli zayıflık", positive=False))

    if ind.ema50 is not None and ind.ema200 is not None:
        if ind.ema50 > ind.ema200:
            score += 6
            reasons.append(Reason(text="EMA50, EMA200 üzerinde", positive=True))
        else:
            reasons.append(
                Reason(text="EMA50, EMA200'ün altında — uzun vadeli düşüş eğilimi", positive=False)
            )

    return min(score, MAX_CATEGORY_SCORE), reasons


def score_momentum(ind: IndicatorSnapshot) -> tuple[int, list[Reason]]:
    score = 0
    reasons: list[Reason] = []

    if ind.rsi14 is not None:
        if 45.0 <= ind.rsi14 <= 65.0:
            score += 8
            reasons.append(Reason(text=f"RSI sağlıklı momentum aralığında ({ind.rsi14:.1f})", positive=True))
        elif ind.rsi14 > 70.0:
            reasons.append(
                Reason(text=f"RSI aşırı alım bölgesinde ({ind.rsi14:.1f}) — geri çekilme riski", positive=False)
            )
        elif ind.rsi14 < 30.0:
            reasons.append(
                Reason(text=f"RSI aşırı satım bölgesinde ({ind.rsi14:.1f}) — baskı sürüyor", positive=False)
            )

    if ind.macd is not None:
        if ind.macd.histogram > 0 and ind.macd.macd_line > ind.macd.signal_line:
            score += 8
            reasons.append(Reason(text="MACD yükseliş sinyali veriyor", positive=True))
        else:
            reasons.append(Reason(text="MACD düşüş sinyali veriyor", positive=False))

    if ind.momentum_roc is not None:
        if ind.momentum_roc > 0:
            score += 4
            reasons.append(
                Reason(text=f"Pozitif momentum: %{ind.momentum_roc:.1f} (10 barlık değişim)", positive=True)
            )
        else:
            reasons.append(
                Reason(text=f"Negatif momentum: %{ind.momentum_roc:.1f} (10 barlık değişim)", positive=False)
            )

    return min(score, MAX_CATEGORY_SCORE), reasons


def score_volume(ind: IndicatorSnapshot) -> tuple[int, list[Reason]]:
    score = 0
    reasons: list[Reason] = []

    if ind.volume_ratio is not None:
        if ind.volume_ratio > 2.0:
            score += 20
            reasons.append(Reason(text=f"Hacim ortalamanın {ind.volume_ratio:.1f} katı", positive=True))
        elif ind.volume_ratio > 1.5:
            score += 14
            reasons.append(Reason(text=f"Hacim ortalamanın {ind.volume_ratio:.1f} katı", positive=True))
        elif ind.volume_ratio > 1.0:
            score += 6
            reasons.append(Reason(text=f"Hacim ortalamanın {ind.volume_ratio:.1f} katı", positive=True))
        else:
            reasons.append(
                Reason(text=f"Hacim ortalamanın altında ({ind.volume_ratio:.1f}x) — düşük ilgi", positive=False)
            )

    return min(score, MAX_CATEGORY_SCORE), reasons


def score_price_action(ind: IndicatorSnapshot) -> tuple[int, list[Reason]]:
    score = 0
    reasons: list[Reason] = []

    if ind.bollinger is not None:
        strong_volume = ind.volume_ratio is not None and ind.volume_ratio > 1.5
        if ind.price >= ind.bollinger.upper:
            score += 12 if strong_volume else 6
            reasons.append(
                Reason(
                    text="Fiyat üst Bollinger bandını kırıyor"
                    + (" (güçlü hacimle)" if strong_volume else ""),
                    positive=True,
                )
            )
        elif ind.price <= ind.bollinger.lower:
            reasons.append(Reason(text="Fiyat alt Bollinger bandına yakın/altında", positive=False))

        if ind.vwap is not None:
            if ind.price > ind.vwap:
                score += 8
                reasons.append(Reason(text="Fiyat VWAP üzerinde", positive=True))
            else:
                reasons.append(Reason(text="Fiyat VWAP altında — zayıf fiyat aksiyonu", positive=False))

    return min(score, MAX_CATEGORY_SCORE), reasons


def score_risk_reward(risk: RiskAnalysis | None) -> tuple[int, list[Reason]]:
    if risk is None:
        return 0, []

    reasons: list[Reason] = []
    ratio = risk.risk_reward_ratio
    if ratio >= 3.0:
        score = 20
    elif ratio >= 2.0:
        score = 15
    elif ratio >= 1.5:
        score = 10
    elif ratio >= 1.0:
        score = 5
    else:
        score = 0

    if score > 0:
        reasons.append(Reason(text=f"Risk/ödül oranı {ratio:.2f}", positive=True))
    else:
        reasons.append(Reason(text=f"Risk/ödül oranı zayıf ({ratio:.2f})", positive=False))

    return min(score, MAX_CATEGORY_SCORE), reasons
