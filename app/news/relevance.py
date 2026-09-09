"""Filters a symbol's cached news headlines down to ones that actually
mention the company, then re-derives a sentiment verdict from only that
relevant subset. This is the news counterpart to
app/fundamentals/long_term_scoring.py: a pure, side-effect-free scoring
function consumed directly by AutoTraderService._passes_news_sentiment,
rather than folded into NewsService itself -- NewsService stays a generic,
market-data-agnostic cache also read unfiltered by the dashboard for a human
to skim; that raw view has its own value and must not change. The
alias-based relevance filter is specific to this one trading decision, so it
lives beside the other domain-scoring modules instead of inside the shared
cache.
"""
from __future__ import annotations

import re

from app.news.models import NewsItem, RelevantNewsVerdict, SentimentLabel, SymbolNewsSummary
from app.news.symbol_aliases import SYMBOL_NAME_ALIASES


def _relevance_patterns(symbol: str) -> list[re.Pattern[str]]:
    needles = SYMBOL_NAME_ALIASES.get(symbol.upper(), [])
    # Word-boundary, same approach as keyword_sentiment.py, so e.g. "Meta"
    # doesn't match inside "Metaverse".
    return [re.compile(rf"\b{re.escape(n)}\b", re.IGNORECASE) for n in needles]


def _is_relevant(item: NewsItem, patterns: list[re.Pattern[str]]) -> bool:
    return any(p.search(item.title) for p in patterns)


def evaluate_relevant_sentiment(summary: SymbolNewsSummary | None, symbol: str) -> RelevantNewsVerdict:
    """Fails open (echoes the unfiltered summary's own overall/counts)
    whenever there's no cached summary or no alias data for this symbol --
    that means "we cannot filter," not "nothing is relevant." Same
    fail-open philosophy as AutoTraderService._passes_long_term_outlook."""
    symbol = symbol.upper()
    if summary is None:
        return RelevantNewsVerdict(
            symbol=symbol, overall=SentimentLabel.UNAVAILABLE,
            relevant_count=0, total_count=0,
            positive_count=0, negative_count=0, neutral_count=0,
            alias_filtered=False,
        )

    if symbol not in SYMBOL_NAME_ALIASES:
        return RelevantNewsVerdict(
            symbol=symbol, overall=summary.overall,
            relevant_count=len(summary.items), total_count=len(summary.items),
            positive_count=summary.positive_count, negative_count=summary.negative_count,
            neutral_count=summary.neutral_count, alias_filtered=False,
        )

    patterns = _relevance_patterns(symbol)
    relevant = [item for item in summary.items if _is_relevant(item, patterns)]
    positive = sum(1 for i in relevant if i.sentiment == SentimentLabel.POSITIVE)
    negative = sum(1 for i in relevant if i.sentiment == SentimentLabel.NEGATIVE)
    neutral = sum(1 for i in relevant if i.sentiment == SentimentLabel.NEUTRAL)

    # Mirrors news_service.py's _summarize() majority-vote rule exactly, on
    # the filtered subset instead of every cached headline -- duplicated
    # rather than shared to keep NewsService (and its unfiltered dashboard
    # display) completely untouched by this feature.
    if positive == 0 and negative == 0 and neutral == 0:
        overall = SentimentLabel.UNAVAILABLE
    elif positive > negative and positive >= neutral:
        overall = SentimentLabel.POSITIVE
    elif negative > positive and negative >= neutral:
        overall = SentimentLabel.NEGATIVE
    else:
        overall = SentimentLabel.NEUTRAL

    return RelevantNewsVerdict(
        symbol=symbol, overall=overall,
        relevant_count=len(relevant), total_count=len(summary.items),
        positive_count=positive, negative_count=negative, neutral_count=neutral,
        alias_filtered=True,
    )
