"""Higher-timeframe (daily bar) trend read — deliberately separate from the
intraday Opportunity Score. See DailyTrend.trend_up's docstring for why: a
1-minute-bar STRONG_BUY_SETUP can fire in the middle of a daily downtrend,
and that's a real, useful distinction for AutoTraderService to see rather
than average away (same rationale as DipOpportunity in app/signals/models.py).
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class DailyTrend(BaseModel):
    symbol: str
    ema50: float | None = None
    ema200: float | None = None
    # True = daily EMA50 above daily EMA200 (uptrend), False = below
    # (downtrend), None = not enough daily history yet to tell.
    trend_up: bool | None = None
    as_of: datetime
