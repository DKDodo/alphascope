from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from app.api.deps import get_market_context
from app.autotrader.autotrader_service import TRANSACTION_COST_RATE
from app.portfolio import portfolio_repository
from app.portfolio.models import ManualTradeRequest

router = APIRouter(prefix="/api/{market}/portfolio", tags=["portfolio"])


@router.get("")
async def get_portfolio(request: Request, market: str) -> dict:
    ctx = get_market_context(request, market)
    db = request.app.state.db
    snapshot = ctx.scanner_service.portfolio.snapshot().model_dump(mode="json")
    snapshot["currency_symbol"] = ctx.currency_symbol
    trades = portfolio_repository.load_recent_trades(db.session_factory, market)
    snapshot["recent_trades"] = [
        {
            "symbol": t.symbol,
            "action": t.action,
            "price": t.price,
            "quantity": t.quantity,
            "realized_pnl": t.realized_pnl,
            "timestamp": t.timestamp.isoformat(),
        }
        for t in trades
    ]
    return snapshot


async def _persist_trade_or_rollback(
    db, market: str, ctx, before, action: str, symbol: str, log_price: float,
    quantity: float, realized_pnl: float | None,
) -> None:
    """Persists the trade log + resulting portfolio state as one atomic
    commit (portfolio_repository.persist_trade), and restores the
    in-memory portfolio to its pre-trade snapshot if that write fails --
    without this, a DB error left the in-memory buy/sell applied (the
    response's own portfolio view would show it) while nothing was ever
    persisted, so a restart silently reverted a trade the user was just
    shown as successful. Runs the blocking SQLite write off the event loop,
    same as every other DB write reachable from an async route here."""
    snapshot = ctx.scanner_service.portfolio.snapshot()
    try:
        await asyncio.to_thread(
            portfolio_repository.persist_trade,
            db.session_factory, market, symbol, action, log_price, quantity, realized_pnl,
            snapshot.cash, {p.symbol: p for p in snapshot.positions}, snapshot.realized_pnl,
        )
    except Exception:
        ctx.scanner_service.portfolio.restore_state(
            before.cash, {p.symbol: p for p in before.positions}, before.realized_pnl
        )
        raise


@router.post("/buy")
async def buy_position(request: Request, market: str, payload: ManualTradeRequest) -> dict:
    ctx = get_market_context(request, market)
    db = request.app.state.db
    symbol = payload.symbol.upper()
    # Price is always resolved server-side from the live signal, never
    # trusted from the client -- same reasoning as AutoTrader, which never
    # accepts a client-supplied fill price either.
    signal = ctx.scanner_service.get_signal(symbol)
    if signal is None:
        raise HTTPException(status_code=400, detail=f"{symbol} için henüz fiyat verisi yok.")

    before = ctx.scanner_service.portfolio.snapshot()
    # Fee applied to the fill (like AutoTrader's own entries), logged at the
    # raw signal price (like AutoTrader's trade log) -- see
    # app/backtest/backtest_engine.py's _record_sell for the same split.
    fill_price = signal.price * (1 + TRANSACTION_COST_RATE)
    ctx.scanner_service.portfolio.buy(symbol, payload.quantity, fill_price)
    await _persist_trade_or_rollback(db, market, ctx, before, "BUY", symbol, signal.price, payload.quantity, None)
    return await get_portfolio(request, market)


@router.post("/sell")
async def sell_position(request: Request, market: str, payload: ManualTradeRequest) -> dict:
    ctx = get_market_context(request, market)
    db = request.app.state.db
    symbol = payload.symbol.upper()
    signal = ctx.scanner_service.get_signal(symbol)
    if signal is None:
        raise HTTPException(status_code=400, detail=f"{symbol} için henüz fiyat verisi yok.")

    before = ctx.scanner_service.portfolio.snapshot()
    fill_price = signal.price * (1 - TRANSACTION_COST_RATE)
    ctx.scanner_service.portfolio.sell(symbol, payload.quantity, fill_price)
    realized_pnl = round(ctx.scanner_service.portfolio.snapshot().realized_pnl - before.realized_pnl, 2)
    await _persist_trade_or_rollback(
        db, market, ctx, before, "SELL", symbol, signal.price, payload.quantity, realized_pnl
    )
    return await get_portfolio(request, market)
