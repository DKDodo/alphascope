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


class DipConfidence(str, Enum):
    STRONG = "STRONG"
    MEDIUM = "MEDIUM"
    WEAK = "WEAK"


class Reason(BaseModel):
    text: str
    positive: bool  # True = score-supporting factor, False = a factor working against the signal


class DipOpportunity(BaseModel):
    """A separate, opt-in 'bought the dip' read — mean-reversion (oversold +
    near support + volume), the opposite lens from the trend-following
    Opportunity Score above. Deliberately never folded into that score: the
    two can and do disagree (a stock can be a textbook AVOID by trend rules
    while also sitting at an oversold support bounce candidate), and hiding
    one inside the other would erase that distinction rather than surface it.
    """

    confidence: DipConfidence
    reasons: list[Reason]


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
    # Age of the most recent bar this score was computed from, in seconds.
    # A large value means the underlying market data hasn't updated in a
    # while — either the market is simply closed (normal) or the data feed
    # has stalled (worth a second look) — see SignalEngine._compute_data_age.
    data_age_seconds: float | None = None
    # Separate mean-reversion read, independent of the trend-following score
    # above — see DipOpportunity's docstring for why these aren't merged.
    dip_opportunity: DipOpportunity | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    disclaimer: str = (
        "Sadece karar destek amaçlıdır. Yatırım tavsiyesi değildir. "
        "Bu sistem üzerinden hiçbir gerçek emir gönderilmez."
    )
