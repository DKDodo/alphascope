"""A MarketContext bundles everything one independent market/tab needs:
its own universe, provider, scanner state, and paper portfolio. 'global'
(mock US-style data) and 'bist' (real, Yahoo-delayed BIST30 data) each run
as a separate context so their symbols, currencies, and provider outages
never interfere with each other.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.autotrader.autotrader_service import AutoTraderService
from app.fundamentals.fundamentals_service import FundamentalsService
from app.news.news_service import NewsService
from app.scanner.universe import Universe
from app.services.market_service import MarketService
from app.services.scanner_service import ScannerService


@dataclass
class MarketContext:
    key: str
    label: str
    currency_symbol: str
    universe: Universe
    market_service: MarketService
    scanner_service: ScannerService
    news_service: NewsService | None = None
    autotrader_service: AutoTraderService | None = None
    fundamentals_service: FundamentalsService | None = None
    note: str | None = None
