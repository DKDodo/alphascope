"""Macro/market-context indicators (USD/TRY, S&P 500, VIX, ...). Purely
informational — never feeds into the Opportunity Score — since the point is
to give the user context a per-symbol technical score can't capture (e.g.
Lira depreciation eating into BIST gains priced in TRY)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class MacroIndicator(BaseModel):
    symbol: str
    label: str
    description: str
    price: float | None
    change_pct: float | None
    as_of: datetime | None
