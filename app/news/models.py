"""News + sentiment models. A sentiment label is a statistical NLP output,
never investment advice — see disclaimers on every API response that carries one.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class SentimentLabel(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    UNAVAILABLE = "UNAVAILABLE"  # sentiment analyzer not installed/loaded


class NewsItem(BaseModel):
    title: str
    publisher: str | None = None
    link: str | None = None
    published_at: datetime | None = None
    sentiment: SentimentLabel = SentimentLabel.UNAVAILABLE
    sentiment_score: float | None = None  # model confidence, 0-1


class SymbolNewsSummary(BaseModel):
    symbol: str
    items: list[NewsItem]
    positive_count: int
    negative_count: int
    neutral_count: int
    overall: SentimentLabel
    sentiment_method: str = "unavailable"  # "finbert" | "keyword" | "unavailable" — shown in the UI for transparency
    disclaimer: str = (
        "Haber duyarlılığı istatistiksel/kural tabanlı bir sınıflandırmadır; "
        "gerçek olayların doğruluğunu teyit etmez ve yatırım tavsiyesi değildir. "
        "Kaynak haberi mutlaka kendiniz okuyun."
    )
