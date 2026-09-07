from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import get_market_context

router = APIRouter(prefix="/api/{market}/portfolio", tags=["portfolio"])


@router.get("")
async def get_portfolio(request: Request, market: str) -> dict:
    ctx = get_market_context(request, market)
    snapshot = ctx.scanner_service.portfolio.snapshot().model_dump(mode="json")
    snapshot["currency_symbol"] = ctx.currency_symbol
    return snapshot
