"""Periodically fetches news + sentiment for every symbol in a market's
universe and caches the result in memory for the API to serve. Runs on its
own slow interval (news doesn't change minute to minute) and, like every
other background loop in AlphaScope, a failure here never stops scanning.
"""
from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.news.models import NewsItem, SentimentLabel, SymbolNewsSummary
from app.news.news_provider import fetch_symbol_news
from app.news.sentiment_analyzer import get_sentiment_analyzer

logger = get_logger(__name__)


class NewsService:
    def __init__(
        self,
        symbols: list[str],
        ticker_suffix: str = "",
        poll_interval_seconds: float = 900.0,
        max_items_per_symbol: int = 8,
    ) -> None:
        self._symbols = symbols
        self._ticker_suffix = ticker_suffix
        self._poll_interval = poll_interval_seconds
        self._max_items = max_items_per_symbol
        self._analyzer = get_sentiment_analyzer()

        self._latest: dict[str, SymbolNewsSummary] = {}
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        self._stopping = False
        self._task = asyncio.create_task(self._loop(), name="news-service")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self._run_cycle()
            except Exception:  # noqa: BLE001 - a news cycle failure must not stop the app
                logger.exception("news cycle failed")
            await asyncio.sleep(self._poll_interval)

    async def _run_cycle(self) -> None:
        per_symbol_items = await asyncio.gather(
            *[
                fetch_symbol_news(symbol, self._ticker_suffix, self._max_items)
                for symbol in self._symbols
            ]
        )

        all_titles = [item.title for items in per_symbol_items for item in items]
        sentiments = await self._analyzer.classify(all_titles) if all_titles else []

        method = self._analyzer.method if all_titles else "unknown"
        cursor = 0
        for symbol, items in zip(self._symbols, per_symbol_items):
            scored_items: list[NewsItem] = []
            for item in items:
                label, score = sentiments[cursor]
                cursor += 1
                scored_items.append(item.model_copy(update={"sentiment": label, "sentiment_score": score}))
            self._latest[symbol] = _summarize(symbol, scored_items, method)

        logger.info(
            "news cycle complete: %d symbols, %d headlines (sentiment method: %s)",
            len(self._symbols), len(all_titles), method,
        )

    def get_news(self, symbol: str) -> SymbolNewsSummary | None:
        return self._latest.get(symbol.upper())


def _summarize(symbol: str, items: list[NewsItem], method: str = "unavailable") -> SymbolNewsSummary:
    positive = sum(1 for i in items if i.sentiment == SentimentLabel.POSITIVE)
    negative = sum(1 for i in items if i.sentiment == SentimentLabel.NEGATIVE)
    neutral = sum(1 for i in items if i.sentiment == SentimentLabel.NEUTRAL)

    if positive == 0 and negative == 0 and neutral == 0:
        overall = SentimentLabel.UNAVAILABLE
    elif positive > negative and positive >= neutral:
        overall = SentimentLabel.POSITIVE
    elif negative > positive and negative >= neutral:
        overall = SentimentLabel.NEGATIVE
    else:
        overall = SentimentLabel.NEUTRAL

    return SymbolNewsSummary(
        symbol=symbol,
        items=items,
        positive_count=positive,
        negative_count=negative,
        neutral_count=neutral,
        overall=overall,
        sentiment_method=method,
    )
