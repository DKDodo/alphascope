from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.risk.position_sizing import PositionSize, calculate_position_size

router = APIRouter(prefix="/api/risk", tags=["risk"])


class PositionSizeRequest(BaseModel):
    account_balance: float
    risk_percent: float
    entry_price: float
    stop_price: float


@router.post("/position-size", response_model=PositionSize)
async def position_size(payload: PositionSizeRequest) -> PositionSize:
    return calculate_position_size(
        account_balance=payload.account_balance,
        risk_percent=payload.risk_percent,
        entry_price=payload.entry_price,
        stop_price=payload.stop_price,
    )
