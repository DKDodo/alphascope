"""Fetches per-symbol fundamental (company-level) data via yfinance.

Same Yahoo Finance source as prices/news — works for both Global and BIST
(".IS") symbols with no extra API key. Company fundamentals change slowly
(quarterly earnings, mostly), so this is meant to be polled far less often
than prices — see FundamentalsService.
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.core.logging import get_logger
from app.fundamentals.models import FundamentalSnapshot

logger = get_logger(__name__)


def _pct(value: Any) -> float | None:
    """yfinance reports ratios (0.15 = 15%) — convert to a plain percentage."""
    if value is None:
        return None
    try:
        return round(float(value) * 100.0, 2)
    except (TypeError, ValueError):
        return None


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _fetch_snapshot_sync(symbol: str, ticker_symbol: str) -> FundamentalSnapshot | None:
    import yfinance as yf

    info = yf.Ticker(ticker_symbol).info
    if not info or info.get("currentPrice") is None and info.get("regularMarketPrice") is None:
        return None

    recommendation = info.get("recommendationKey")
    if recommendation in (None, "none", ""):
        recommendation = None

    return FundamentalSnapshot(
        symbol=symbol,
        long_name=info.get("longName") or info.get("shortName"),
        sector=info.get("sector"),
        trailing_pe=_num(info.get("trailingPE")),
        forward_pe=_num(info.get("forwardPE")),
        price_to_book=_num(info.get("priceToBook")),
        profit_margin_pct=_pct(info.get("profitMargins")),
        ebitda_margin_pct=_pct(info.get("ebitdaMargins")),
        revenue_growth_pct=_pct(info.get("revenueGrowth")),
        return_on_equity_pct=_pct(info.get("returnOnEquity")),
        debt_to_equity=_num(info.get("debtToEquity")),
        analyst_recommendation=recommendation,
        analyst_target_price=_num(info.get("targetMeanPrice")),
        current_price=_num(info.get("currentPrice") or info.get("regularMarketPrice")),
        market_cap=_num(info.get("marketCap")),
        book_value_per_share=_num(info.get("bookValue")),
        net_income=_num(info.get("netIncomeToCommon")),
    )


async def fetch_fundamental_snapshot(symbol: str, ticker_suffix: str = "") -> FundamentalSnapshot | None:
    ticker_symbol = f"{symbol}{ticker_suffix}"
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _fetch_snapshot_sync, symbol, ticker_symbol)
    except Exception:  # noqa: BLE001 - a fundamentals outage must not affect scanning/signals
        logger.exception("failed to fetch fundamentals for %s", ticker_symbol)
        return None
