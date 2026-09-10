from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from app.api.deps import get_market_context
from app.backtest.backtest_engine import run_backtest
from app.backtest.models import BacktestRequest

router = APIRouter(prefix="/api/{market}/backtest", tags=["backtest"])

# Static per-market config the backtest engine needs but MarketContext
# doesn't carry -- same spirit as the hardcoded macro_indicators lists in
# app/main.py's lifespan(). BIST has no ^VIX in its macro indicators today
# (see autotrader_service.py's fail-open VIX handling), so it's left out
# of the VIX-available set rather than faked.
_TICKER_SUFFIX_BY_MARKET: dict[str, str] = {"global": "", "bist": ".IS", "crypto": "-USD"}
_BENCHMARK_BY_MARKET: dict[str, str] = {"global": "^GSPC", "bist": "XU100.IS", "crypto": "BTC-USD"}
_VIX_AVAILABLE_MARKETS: frozenset[str] = frozenset({"global", "crypto"})


@router.post("/run")
async def run_market_backtest(request: Request, market: str, payload: BacktestRequest) -> dict:
    ctx = get_market_context(request, market)
    # run_backtest() is fully synchronous -- several blocking yf.download
    # calls plus a CPU-bound day-by-day replay loop over years of history --
    # unlike every other yfinance call site in this codebase, it wasn't
    # wrapped in asyncio.to_thread. Run directly on the event loop, this
    # froze the entire app (every other request, every market's AutoTrader
    # tick) for the whole backtest duration.
    result = await asyncio.to_thread(
        run_backtest,
        market=market,
        symbols=ctx.universe.symbols,
        ticker_suffix=_TICKER_SUFFIX_BY_MARKET.get(market, ""),
        benchmark_symbol=_BENCHMARK_BY_MARKET.get(market),
        vix_available=market in _VIX_AVAILABLE_MARKETS,
        initial_cash=payload.initial_cash,
        years=payload.years,
    )
    if result.symbols_included == 0:
        raise HTTPException(
            status_code=502,
            detail="Geçmiş veri alınamadı (Yahoo Finance'ten yanıt gelmedi). Lütfen daha sonra tekrar deneyin.",
        )
    return result.model_dump(mode="json")
