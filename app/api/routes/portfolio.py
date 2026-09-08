from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.api.deps import get_market_context
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


def _persist(db, market: str, ctx) -> None:
    snapshot = ctx.scanner_service.portfolio.snapshot()
    portfolio_repository.save_snapshot(
        db.session_factory, market, snapshot.cash,
        {p.symbol: p for p in snapshot.positions}, snapshot.realized_pnl,
    )


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

    ctx.scanner_service.portfolio.buy(symbol, payload.quantity, signal.price)
    _persist(db, market, ctx)
    portfolio_repository.record_trade(
        db.session_factory, market, symbol, "BUY", signal.price, payload.quantity, None
    )
    return await get_portfolio(request, market)


@router.post("/sell")
async def sell_position(request: Request, market: str, payload: ManualTradeRequest) -> dict:
    ctx = get_market_context(request, market)
    db = request.app.state.db
    symbol = payload.symbol.upper()
    signal = ctx.scanner_service.get_signal(symbol)
    if signal is None:
        raise HTTPException(status_code=400, detail=f"{symbol} için henüz fiyat verisi yok.")

    before_pnl = ctx.scanner_service.portfolio.snapshot().realized_pnl
    ctx.scanner_service.portfolio.sell(symbol, payload.quantity, signal.price)
    after_pnl = ctx.scanner_service.portfolio.snapshot().realized_pnl
    _persist(db, market, ctx)
    portfolio_repository.record_trade(
        db.session_factory, market, symbol, "SELL", signal.price, payload.quantity,
        round(after_pnl - before_pnl, 2),
    )
    return await get_portfolio(request, market)
