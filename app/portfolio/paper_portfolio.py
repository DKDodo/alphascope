"""Virtual-only paper trading portfolio. No real order is ever sent from here."""
from __future__ import annotations

import math

from app.core.exceptions import RiskCalculationError
from app.portfolio.models import PortfolioSnapshot, Position


class PaperPortfolio:
    def __init__(self, starting_cash: float = 100_000.0) -> None:
        self._cash = starting_cash
        self._positions: dict[str, Position] = {}
        self._realized_pnl = 0.0

    def restore_state(self, cash: float, positions: dict[str, Position], realized_pnl: float) -> None:
        """Overwrites in-memory state from persisted data -- same idea as
        ScannerEngine.seed_bar(): a pure state load, no I/O here (see
        app/portfolio/portfolio_repository.py for the actual DB read).
        Used to warm-start from a previous run so a restart doesn't wipe
        out the user's manual positions."""
        self._cash = cash
        self._positions = dict(positions)
        self._realized_pnl = realized_pnl

    def buy(self, symbol: str, quantity: float, price: float) -> Position:
        # isfinite() rejects NaN/inf alongside the plain <=0 check -- NaN
        # compares False against everything (quantity<=0 alone lets it
        # through), and a NaN/inf quantity here would make cost=quantity*price
        # NaN/inf too, silently defeating the "cost > cash" guard just below
        # in the same way. The API layer (ManualTradeRequest) already
        # rejects these before they reach here; this is the same guarantee
        # enforced at the class's own boundary, for any other caller.
        if not math.isfinite(quantity) or quantity <= 0:
            raise RiskCalculationError("Adet sıfırdan büyük olmalı.")
        cost = quantity * price
        if cost > self._cash:
            raise RiskCalculationError("Bu emir için yeterli kağıt nakit yok.")

        self._cash -= cost
        existing = self._positions.get(symbol)
        if existing is None:
            position = Position(symbol=symbol, quantity=quantity, average_price=price, current_price=price)
        else:
            total_quantity = existing.quantity + quantity
            total_cost = existing.average_price * existing.quantity + cost
            position = Position(
                symbol=symbol,
                quantity=total_quantity,
                average_price=total_cost / total_quantity,
                current_price=price,
            )
        self._positions[symbol] = position
        return position

    def sell(self, symbol: str, quantity: float, price: float) -> Position | None:
        # Same isfinite()+positivity guard as buy(). Without it, a negative
        # quantity always satisfied "quantity <= existing.quantity" (the
        # only check that used to exist here), bypassing ownership entirely
        # and fabricating shares/cash out of nothing.
        if not math.isfinite(quantity) or quantity <= 0:
            raise RiskCalculationError("Adet sıfırdan büyük olmalı.")
        existing = self._positions.get(symbol)
        if existing is None or quantity > existing.quantity:
            raise RiskCalculationError("Elinizdeki pozisyondan fazlasını satamazsınız.")

        self._realized_pnl += (price - existing.average_price) * quantity
        self._cash += quantity * price

        remaining = existing.quantity - quantity
        if remaining <= 0:
            del self._positions[symbol]
            return None

        position = Position(
            symbol=symbol,
            quantity=remaining,
            average_price=existing.average_price,
            current_price=price,
        )
        self._positions[symbol] = position
        return position

    def update_market_price(self, symbol: str, price: float) -> None:
        existing = self._positions.get(symbol)
        if existing is not None:
            self._positions[symbol] = existing.model_copy(update={"current_price": price})

    def snapshot(self) -> PortfolioSnapshot:
        positions = list(self._positions.values())
        unrealized = sum(p.unrealized_pnl for p in positions)
        equity = self._cash + sum(p.market_value for p in positions)
        return PortfolioSnapshot(
            cash=round(self._cash, 2),
            positions=positions,
            realized_pnl=round(self._realized_pnl, 2),
            unrealized_pnl=round(unrealized, 2),
            equity=round(equity, 2),
        )
