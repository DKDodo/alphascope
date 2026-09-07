from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import get_market_context

router = APIRouter(prefix="/api/{market}/macro", tags=["macro"])


@router.get("")
async def get_macro_indicators(request: Request, market: str) -> list[dict]:
    ctx = get_market_context(request, market)
    if ctx.macro_service is None:
        return []
    return [i.model_dump(mode="json") for i in ctx.macro_service.get_indicators()]
