from __future__ import annotations

from fastapi import HTTPException, Request

from app.services.market_context import MarketContext


def get_market_context(request: Request, market: str) -> MarketContext:
    contexts: dict[str, MarketContext] = request.app.state.market_contexts
    ctx = contexts.get(market)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"Bilinmeyen piyasa: '{market}'")
    return ctx
