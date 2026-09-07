"""Fundamental (company-level) data and the long-term outlook derived from
it. Kept fully separate from the short-term technical Opportunity Score —
see long_term_scoring.py for why they're never blended into one number.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from app.signals.models import Reason


class LongTermOutlookLabel(str, Enum):
    FAVORABLE = "FAVORABLE"
    NEUTRAL = "NEUTRAL"
    UNFAVORABLE = "UNFAVORABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class FundamentalSnapshot(BaseModel):
    symbol: str
    long_name: str | None = None
    sector: str | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    profit_margin_pct: float | None = None
    revenue_growth_pct: float | None = None
    return_on_equity_pct: float | None = None
    debt_to_equity: float | None = None
    analyst_recommendation: str | None = None  # Yahoo's own consensus label, verbatim
    analyst_target_price: float | None = None
    current_price: float | None = None


class LongTermOutlook(BaseModel):
    symbol: str
    label: LongTermOutlookLabel
    score: int  # 0-100, same scale as the short-term score but never combined with it
    reasons: list[Reason]
    fundamentals: FundamentalSnapshot | None = None
    long_term_trend_up: bool | None = None  # EMA50 > EMA200
    disclaimer: str = (
        "Uzun vadeli görünüm, şirket temel verileri (F/K, kâr marjı, büyüme, "
        "analist konsensüsü) ve uzun vadeli trend yönünden türetilen kural "
        "tabanlı bir değerlendirmedir; kısa vadeli Fırsat Skoru ile karıştırılmamalıdır. "
        "Temel veriler eksik/gecikmeli olabilir ve bu yatırım tavsiyesi değildir."
    )
