"""The set of symbols the scanner tracks. Backed by MockProvider's default
universe today; swapping in a larger list (or per-exchange lists once BIST/
NYSE/NASDAQ providers exist) does not require touching the scanner itself.
"""
from __future__ import annotations

from app.market_data.models import AssetClass
from app.market_data.providers.mock_provider import DEFAULT_SYMBOLS


class Universe:
    def __init__(
        self,
        symbols: list[str] | None = None,
        asset_class: AssetClass = AssetClass.EQUITY,
        exchange: str = "MOCK",
    ) -> None:
        self._symbols = list(symbols or DEFAULT_SYMBOLS)
        self._asset_class = asset_class
        self._exchange = exchange

    @property
    def symbols(self) -> list[str]:
        return list(self._symbols)

    @property
    def asset_class(self) -> AssetClass:
        return self._asset_class

    @property
    def exchange(self) -> str:
        return self._exchange

    def __contains__(self, symbol: str) -> bool:
        return symbol in self._symbols
