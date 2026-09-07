from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.api.deps import get_market_context

router = APIRouter(prefix="/api/{market}/news", tags=["news"])


@router.get("/{symbol}")
async def get_symbol_news(request: Request, market: str, symbol: str) -> dict:
    ctx = get_market_context(request, market)
    if ctx.news_service is None:
        raise HTTPException(status_code=404, detail="Bu sunucuda haber özelliği devre dışı (NEWS_ENABLED=false)")
    summary = ctx.news_service.get_news(symbol.upper())
    if summary is None:
        raise HTTPException(status_code=404, detail=f"'{symbol.upper()}' için henüz haber toplanmadı")
    return summary.model_dump(mode="json")
