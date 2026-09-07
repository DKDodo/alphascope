from __future__ import annotations

from fastapi import APIRouter, Request

from app.services.market_context import MarketContext

router = APIRouter(prefix="/api/markets", tags=["markets"])


@router.get("")
async def list_markets(request: Request) -> list[dict]:
    contexts: dict[str, MarketContext] = request.app.state.market_contexts
    return [
        {
            "key": ctx.key,
            "label": ctx.label,
            "currency_symbol": ctx.currency_symbol,
            "note": ctx.note,
        }
        for ctx in contexts.values()
    ]
