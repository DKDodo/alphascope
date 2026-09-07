from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.api.deps import get_market_context

router = APIRouter(prefix="/api/{market}/fundamentals", tags=["fundamentals"])


@router.get("/{symbol}")
async def get_long_term_outlook(request: Request, market: str, symbol: str) -> dict:
    ctx = get_market_context(request, market)
    if ctx.fundamentals_service is None:
        raise HTTPException(status_code=404, detail="Bu piyasada temel analiz özelliği devre dışı")
    outlook = ctx.fundamentals_service.get_long_term_outlook(symbol)
    return outlook.model_dump(mode="json")
