from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.api.deps import get_market_context

router = APIRouter(prefix="/api/{market}/signals", tags=["signals"])


@router.get("/{symbol}")
async def get_signal(request: Request, market: str, symbol: str) -> dict:
    ctx = get_market_context(request, market)
    result = ctx.scanner_service.get_signal(symbol.upper())
    if result is None:
        raise HTTPException(status_code=404, detail=f"'{symbol.upper()}' için henüz sinyal üretilmedi")
    return result.model_dump(mode="json")
