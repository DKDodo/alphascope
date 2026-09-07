from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.api.deps import get_market_context
from app.signals.models import SignalType

router = APIRouter(prefix="/api/{market}/scanner", tags=["scanner"])


@router.get("")
async def scan(
    request: Request,
    market: str,
    min_score: int = Query(default=0, ge=0, le=100),
    signal: SignalType | None = None,
) -> list[dict]:
    ctx = get_market_context(request, market)
    results = ctx.scanner_service.get_scan_results()

    filtered = [r for r in results if r.score >= min_score and (signal is None or r.signal == signal)]
    filtered.sort(key=lambda r: r.score, reverse=True)

    return [
        {
            "symbol": r.symbol,
            "price": r.price,
            "signal": r.signal.value,
            "score": r.score,
            "risk_level": r.risk_level.value,
        }
        for r in filtered
    ]
