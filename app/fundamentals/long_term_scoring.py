"""Deterministic, rule-based long-term outlook scoring — the fundamentals
counterpart to app/signals/scoring.py's short-term technical scoring.

Deliberately kept SEPARATE from the short-term Opportunity Score rather than
blended into one number: a stock can be a good short-term technical setup
and a poor long-term fundamental story (or vice versa), and collapsing that
into a single score would hide the distinction the user explicitly asked for.

Thresholds (P/E bands, margin/growth cutoffs, debt/equity levels) are common
rule-of-thumb heuristics, not a peer-reviewed valuation model — they're
transparent and overridable by reading this file, not a black box.
"""
from __future__ import annotations

from app.fundamentals.models import (
    FundamentalSnapshot,
    LongTermOutlook,
    LongTermOutlookLabel,
)
from app.signals.models import Reason

MAX_CATEGORY_SCORE = 20

_POSITIVE_RECOMMENDATIONS = {"strong_buy", "buy"}
_NEGATIVE_RECOMMENDATIONS = {"sell", "strong_sell", "underperform"}


def score_valuation(f: FundamentalSnapshot) -> tuple[int, list[Reason]]:
    pe = f.trailing_pe or f.forward_pe
    if pe is None:
        return 0, []
    if pe <= 0:
        return 0, [Reason(text="F/K oranı negatif (şirket zarar ediyor)", positive=False)]
    if pe < 15:
        return 20, [Reason(text=f"F/K oranı düşük/makul ({pe:.1f}) — ucuz değerleme", positive=True)]
    if pe < 25:
        return 12, [Reason(text=f"F/K oranı makul aralıkta ({pe:.1f})", positive=True)]
    if pe < 40:
        return 0, []
    return 0, [Reason(text=f"F/K oranı yüksek ({pe:.1f}) — pahalı değerleme", positive=False)]


def score_profitability(f: FundamentalSnapshot) -> tuple[int, list[Reason]]:
    score = 0
    reasons: list[Reason] = []
    if f.profit_margin_pct is not None:
        if f.profit_margin_pct > 15:
            score += 10
            reasons.append(Reason(text=f"Net kâr marjı güçlü (%{f.profit_margin_pct:.1f})", positive=True))
        elif f.profit_margin_pct < 0:
            reasons.append(Reason(text=f"Net kâr marjı negatif (%{f.profit_margin_pct:.1f})", positive=False))
    if f.return_on_equity_pct is not None:
        if f.return_on_equity_pct > 15:
            score += 10
            reasons.append(Reason(text=f"Özkaynak kârlılığı (ROE) güçlü (%{f.return_on_equity_pct:.1f})", positive=True))
        elif f.return_on_equity_pct < 0:
            reasons.append(Reason(text=f"Özkaynak kârlılığı (ROE) negatif (%{f.return_on_equity_pct:.1f})", positive=False))
    return min(score, MAX_CATEGORY_SCORE), reasons


def score_growth(f: FundamentalSnapshot) -> tuple[int, list[Reason]]:
    if f.revenue_growth_pct is None:
        return 0, []
    if f.revenue_growth_pct > 10:
        return 20, [Reason(text=f"Gelir büyümesi güçlü (%{f.revenue_growth_pct:.1f} yıllık)", positive=True)]
    if f.revenue_growth_pct > 0:
        return 10, [Reason(text=f"Gelir büyümesi pozitif (%{f.revenue_growth_pct:.1f} yıllık)", positive=True)]
    return 0, [Reason(text=f"Gelir daralıyor (%{f.revenue_growth_pct:.1f} yıllık)", positive=False)]


def score_financial_health(f: FundamentalSnapshot) -> tuple[int, list[Reason]]:
    if f.debt_to_equity is None:
        return 0, []
    if f.debt_to_equity < 50:
        return 20, [Reason(text=f"Borç/özkaynak oranı düşük ({f.debt_to_equity:.0f}) — sağlam bilanço", positive=True)]
    if f.debt_to_equity < 100:
        return 10, [Reason(text=f"Borç/özkaynak oranı makul ({f.debt_to_equity:.0f})", positive=True)]
    if f.debt_to_equity < 150:
        return 0, []
    return 0, [Reason(text=f"Borç/özkaynak oranı yüksek ({f.debt_to_equity:.0f}) — kaldıraç riski", positive=False)]


def score_recommendation_and_trend(
    f: FundamentalSnapshot, long_term_trend_up: bool | None
) -> tuple[int, list[Reason]]:
    score = 0
    reasons: list[Reason] = []
    if f.analyst_recommendation is not None:
        rec = f.analyst_recommendation.lower()
        if rec in _POSITIVE_RECOMMENDATIONS:
            score += 10
            reasons.append(Reason(text=f"Analist konsensüsü olumlu ({f.analyst_recommendation})", positive=True))
        elif rec in _NEGATIVE_RECOMMENDATIONS:
            reasons.append(Reason(text=f"Analist konsensüsü olumsuz ({f.analyst_recommendation})", positive=False))
    if long_term_trend_up is not None:
        if long_term_trend_up:
            score += 10
            reasons.append(Reason(text="Uzun vadeli trend yukarı (EMA50, EMA200 üzerinde)", positive=True))
        else:
            reasons.append(Reason(text="Uzun vadeli trend aşağı (EMA50, EMA200 altında)", positive=False))
    return min(score, MAX_CATEGORY_SCORE), reasons


def _classify(score: int) -> LongTermOutlookLabel:
    if score >= 65:
        return LongTermOutlookLabel.FAVORABLE
    if score >= 35:
        return LongTermOutlookLabel.NEUTRAL
    return LongTermOutlookLabel.UNFAVORABLE


def evaluate_long_term_outlook(
    fundamentals: FundamentalSnapshot | None, long_term_trend_up: bool | None
) -> LongTermOutlook:
    symbol = fundamentals.symbol if fundamentals is not None else "UNKNOWN"

    if fundamentals is None:
        return LongTermOutlook(
            symbol=symbol, label=LongTermOutlookLabel.INSUFFICIENT_DATA, score=0,
            reasons=[], fundamentals=None, long_term_trend_up=long_term_trend_up,
        )

    valuation_score, valuation_reasons = score_valuation(fundamentals)
    profitability_score, profitability_reasons = score_profitability(fundamentals)
    growth_score, growth_reasons = score_growth(fundamentals)
    health_score, health_reasons = score_financial_health(fundamentals)
    rec_score, rec_reasons = score_recommendation_and_trend(fundamentals, long_term_trend_up)

    total_score = valuation_score + profitability_score + growth_score + health_score + rec_score
    reasons = [*valuation_reasons, *profitability_reasons, *growth_reasons, *health_reasons, *rec_reasons]

    has_any_data = any([
        fundamentals.trailing_pe, fundamentals.forward_pe, fundamentals.profit_margin_pct,
        fundamentals.revenue_growth_pct, fundamentals.debt_to_equity, fundamentals.analyst_recommendation,
    ])
    label = _classify(total_score) if has_any_data else LongTermOutlookLabel.INSUFFICIENT_DATA

    return LongTermOutlook(
        symbol=symbol, label=label, score=total_score, reasons=reasons,
        fundamentals=fundamentals, long_term_trend_up=long_term_trend_up,
    )
