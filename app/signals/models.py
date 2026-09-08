"""Signal output models. A BUY_SETUP/STRONG_BUY_SETUP signal is a decision-
support label, never a guarantee or investment advice.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from app.risk.risk_engine import RiskAnalysis, RiskLevel


class SignalType(str, Enum):
    STRONG_BUY_SETUP = "STRONG_BUY_SETUP"
    BUY_SETUP = "BUY_SETUP"
    WATCH = "WATCH"
    NEUTRAL = "NEUTRAL"
    AVOID = "AVOID"


class Reason(BaseModel):
    text: str
    positive: bool  # True = score-supporting factor, False = a factor working against the signal


class CategoryScores(BaseModel):
    trend: int = Field(ge=0, le=20)
    momentum: int = Field(ge=0, le=20)
    volume: int = Field(ge=0, le=20)
    price_action: int = Field(ge=0, le=20)
    risk_reward: int = Field(ge=0, le=20)

    @property
    def total(self) -> int:
        return self.trend + self.momentum + self.volume + self.price_action + self.risk_reward


class SignalResult(BaseModel):
    symbol: str
    price: float
    score: int = Field(ge=0, le=100)
    signal: SignalType
    reasons: list[Reason]
    risk_level: RiskLevel
    category_scores: CategoryScores
    risk_analysis: RiskAnalysis | None = None
    # A rough 'attractive pullback' reference band, derived from current
    # volatility/trend — not a guarantee the price will reach it.
    buy_zone_low: float | None = None
    buy_zone_high: float | None = None
    # How many rolling bars the scanner has accumulated for this symbol.
    # EMA200 needs 200, MACD needs ~35 — a low number here (and staying low
    # over time) means the score is capped by missing data, not a real
    # "avoid" read on the market.
    bars_available: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    disclaimer: str = (
        "Sadece karar destek amaçlıdır. Yatırım tavsiyesi değildir. "
        "Bu sistem üzerinden hiçbir gerçek emir gönderilmez."
    )
