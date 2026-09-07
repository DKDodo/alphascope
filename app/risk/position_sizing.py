"""Fixed-fractional position sizing (paper trading only)."""
from __future__ import annotations

from pydantic import BaseModel

from app.core.exceptions import RiskCalculationError


class PositionSize(BaseModel):
    shares: float
    risk_amount: float
    position_value: float


def calculate_position_size(
    account_balance: float,
    risk_percent: float,
    entry_price: float,
    stop_price: float,
) -> PositionSize:
    """Size a position so that a stop-out risks at most `risk_percent` of `account_balance`."""
    if account_balance <= 0:
        raise RiskCalculationError("account_balance must be positive")
    if not (0 < risk_percent <= 100):
        raise RiskCalculationError("risk_percent must be between 0 and 100")
    if entry_price <= 0:
        raise RiskCalculationError("entry_price must be positive")

    per_share_risk = abs(entry_price - stop_price)
    if per_share_risk == 0:
        raise RiskCalculationError("entry_price and stop_price cannot be equal")

    risk_amount = account_balance * (risk_percent / 100.0)
    shares = risk_amount / per_share_risk
    position_value = shares * entry_price

    return PositionSize(
        shares=round(shares, 4),
        risk_amount=round(risk_amount, 2),
        position_value=round(position_value, 2),
    )
