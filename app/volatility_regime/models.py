"""Self-computed realized-volatility risk derating -- in place of VIX for
markets that never had one (BIST) or were borrowing an ill-fitting one
(Crypto used real S&P ^VIX; see autotrader_service.py's _risk_multiplier
docstring for why that was replaced, confirmed by backtest, not assumed).
Global keeps reading real ^VIX -- this module isn't wired up for it.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class VolatilityRegime(BaseModel):
    benchmark_symbol: str
    realized_vol_pct: float | None = None  # 20-day annualized realized volatility of the benchmark
    # Where today's realized_vol sits in its own trailing history, 0-100 --
    # informational (mirrors what a VIX reading conveys at a glance), not
    # itself the threshold decision (that's done against raw percentile
    # cutoffs -- see volatility_regime_provider.py -- so this can lag the
    # actual classification by rounding).
    percentile_rank: float | None = None
    # Same two-tier scheme VIX-based derating already used
    # (VIX_ELEVATED_THRESHOLD/VIX_HIGH_THRESHOLD in autotrader_service.py):
    # 1.0 normally, 0.5 above the trailing 80th percentile, 0.25 above the
    # 95th. Stays 1.0 (no derating) without enough history yet -- fail
    # open, same spirit as every other optional gate in this codebase.
    risk_multiplier: float = 1.0
    as_of: datetime
