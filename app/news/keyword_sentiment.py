"""Lightweight keyword-based sentiment fallback — no torch/transformers, no
model download, near-zero memory. Used automatically when FinBERT isn't
available (this is what the free web deploy runs on; the desktop build
prefers FinBERT and only falls back to this if that fails to load too).

This is deliberately crude — a word list, not a language model — and is
labeled as such everywhere it's surfaced (see SymbolNewsSummary.sentiment_method)
so it's never mistaken for the more accurate FinBERT classification.
"""
from __future__ import annotations

import re

from app.news.models import SentimentLabel

_POSITIVE_WORDS = [
    "surge", "surges", "surged", "beat", "beats", "beating", "record profit", "growth",
    "upgrade", "upgraded", "outperform", "rally", "rallies", "gain", "gains", "strong",
    "soar", "soars", "soared", "jump", "jumps", "jumped", "buy rating", "bullish",
    "raises guidance", "exceeds expectations", "profit rose", "revenue rose", "wins",
    "expands", "expansion", "breakthrough", "record high", "boost", "boosts", "rebound",
    "recovery", "optimistic", "upbeat", "top estimates", "beat estimates",
]
_NEGATIVE_WORDS = [
    "plunge", "plunges", "plunged", "miss", "misses", "missed", "downgrade", "downgraded",
    "underperform", "lawsuit", "investigation", "bankruptcy", "recall", "layoff", "layoffs",
    "cut guidance", "warns", "warning", "decline", "declines", "slump", "sell rating",
    "bearish", "fraud", "loss", "losses", "crash", "crashes", "plummet", "plummets",
    "scandal", "probe", "cuts jobs", "restructuring", "delisted", "default", "sued",
    "weak demand", "disappointing", "shortfall", "below estimates", "sell-off", "selloff",
]

# Word-boundary patterns, so "beat" doesn't also match inside "beats"/"beating"
# (a plain substring count would double up on shared roots like that).
_POSITIVE_PATTERNS = [re.compile(rf"\b{re.escape(p)}\b") for p in _POSITIVE_WORDS]
_NEGATIVE_PATTERNS = [re.compile(rf"\b{re.escape(p)}\b") for p in _NEGATIVE_WORDS]


def classify_keyword_sync(text: str) -> tuple[SentimentLabel, float]:
    lowered = text.lower()

    positive_hits = sum(1 for pattern in _POSITIVE_PATTERNS if pattern.search(lowered))
    negative_hits = sum(1 for pattern in _NEGATIVE_PATTERNS if pattern.search(lowered))

    net = positive_hits - negative_hits
    confidence = min(1.0, abs(net) / 3.0) if net != 0 else 0.3

    if net > 0:
        return SentimentLabel.POSITIVE, confidence
    if net < 0:
        return SentimentLabel.NEGATIVE, confidence
    return SentimentLabel.NEUTRAL, confidence
