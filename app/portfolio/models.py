"""Paper portfolio data models. Nothing here ever touches a real brokerage."""
from __future__ import annotations

from pydantic import BaseModel


class Position(BaseModel):
    symbol: str
    quantity: float
    average_price: float
    current_price: float | None = None

    @property
    def market_value(self) -> float:
        price = self.current_price if self.current_price is not None else self.average_price
        return self.quantity * price

    @property
    def unrealized_pnl(self) -> float:
        price = self.current_price if self.current_price is not None else self.average_price
        return (price - self.average_price) * self.quantity


class PortfolioSnapshot(BaseModel):
    cash: float
    positions: list[Position]
    realized_pnl: float
    unrealized_pnl: float
    equity: float
