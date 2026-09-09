"""Paper portfolio data models. Nothing here ever touches a real brokerage."""
from __future__ import annotations

from pydantic import BaseModel, Field


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


class ManualTradeRequest(BaseModel):
    symbol: str
    # gt=0 rejects zero/negative/NaN (Pydantic's own comparison already
    # treats NaN as failing "> 0"); allow_inf_nan=False additionally rejects
    # +/-inf, which gt=0 alone would let through for the positive case.
    # Without this, a negative quantity bypassed PaperPortfolio.sell()'s
    # ownership check entirely (quantity > existing.quantity is False for
    # any negative quantity) and a NaN quantity made every cost comparison
    # in buy()/sell() silently evaluate to False, permanently corrupting
    # the shared cash balance to NaN once persisted.
    quantity: float = Field(gt=0, allow_inf_nan=False)
