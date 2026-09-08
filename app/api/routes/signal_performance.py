from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import get_market_context
from app.signals import tracking_repository

router = APIRouter(prefix="/api/{market}/signal-performance", tags=["signal-performance"])


@router.get("")
async def get_signal_performance(request: Request, market: str) -> list[dict]:
    ctx = get_market_context(request, market)
    db = request.app.state.db
    return tracking_repository.get_performance_summary(db.session_factory, ctx.key)
