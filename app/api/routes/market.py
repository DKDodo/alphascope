from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import get_market_context

router = APIRouter(prefix="/api/{market}/symbols", tags=["market"])


@router.get("")
async def list_symbols(request: Request, market: str) -> list[dict[str, str]]:
    ctx = get_market_context(request, market)
    return [
        {"symbol": symbol, "asset_class": ctx.universe.asset_class.value}
        for symbol in ctx.universe.symbols
    ]
