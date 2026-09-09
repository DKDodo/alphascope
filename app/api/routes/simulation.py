from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from app.api.deps import get_market_context
from app.autotrader.models import StartSimulationRequest

router = APIRouter(prefix="/api/{market}/simulation", tags=["simulation"])


@router.get("/status")
async def get_simulation_status(request: Request, market: str) -> dict:
    ctx = get_market_context(request, market)
    if ctx.autotrader_service is None:
        raise HTTPException(status_code=404, detail="Bu piyasada simülasyon özelliği devre dışı")
    return ctx.autotrader_service.get_status().model_dump(mode="json")


@router.post("/start")
async def start_simulation(request: Request, market: str, payload: StartSimulationRequest) -> dict:
    ctx = get_market_context(request, market)
    if ctx.autotrader_service is None:
        raise HTTPException(status_code=404, detail="Bu piyasada simülasyon özelliği devre dışı")
    # Run on a worker thread, not directly on the event loop -- start_run()
    # blocks on ctx.autotrader_service's own lock (see AutoTraderService.__init__)
    # whenever a tick is mid-commit, and this keeps that wait off the event
    # loop so it can't stall every other request in the meantime.
    result = await asyncio.to_thread(
        ctx.autotrader_service.start_run,
        initial_cash=payload.initial_cash,
        duration_days=payload.duration_days,
        stop_loss_pct=payload.stop_loss_pct,
        take_profit_pct=payload.take_profit_pct,
    )
    return result.model_dump(mode="json")


@router.post("/stop")
async def stop_simulation(request: Request, market: str) -> dict:
    ctx = get_market_context(request, market)
    if ctx.autotrader_service is None:
        raise HTTPException(status_code=404, detail="Bu piyasada simülasyon özelliği devre dışı")
    # Same reasoning as /start above -- off the event loop so a concurrent
    # tick's lock hold only delays this request, not every other one.
    result = await asyncio.to_thread(ctx.autotrader_service.stop_run)
    return result.model_dump(mode="json")
