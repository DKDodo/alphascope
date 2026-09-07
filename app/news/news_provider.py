"""Fetches per-symbol news headlines via yfinance (Yahoo Finance).

Works for both Global (NASDAQ/NYSE-style) and BIST (".IS") symbols since
both are ultimately Yahoo tickers. Runs the blocking yfinance call in a
thread executor so it never blocks the event loop.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from app.core.logging import get_logger
from app.news.models import NewsItem

logger = get_logger(__name__)


def _parse_published_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _fetch_symbol_news_sync(ticker_symbol: str, max_items: int) -> list[NewsItem]:
    import yfinance as yf

    raw_items = yf.Ticker(ticker_symbol).news or []
    items: list[NewsItem] = []
    for raw in raw_items[:max_items]:
        content = raw.get("content", raw)  # tolerate older yfinance's flat shape too
        title = content.get("title")
        if not title:
            continue
        url = (content.get("canonicalUrl") or {}).get("url") or (content.get("clickThroughUrl") or {}).get("url")
        provider = (content.get("provider") or {}).get("displayName")
        items.append(
            NewsItem(
                title=title,
                publisher=provider,
                link=url,
                published_at=_parse_published_at(content.get("pubDate")),
            )
        )
    return items


async def fetch_symbol_news(
    symbol: str, ticker_suffix: str = "", max_items: int = 8
) -> list[NewsItem]:
    ticker_symbol = f"{symbol}{ticker_suffix}"
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _fetch_symbol_news_sync, ticker_symbol, max_items)
    except Exception:  # noqa: BLE001 - a news outage must not affect scanning/signals
        logger.exception("failed to fetch news for %s", ticker_symbol)
        return []
