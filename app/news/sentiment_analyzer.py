"""FinBERT-based news sentiment classification, run locally (no API key, no
data leaves the machine). Optional dependency: if `transformers`/`torch`
aren't installed, or the model fails to load (e.g. no internet on first
run), the analyzer degrades to SentimentLabel.UNAVAILABLE instead of
crashing anything — news headlines are still shown, just unscored.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

from app.core.logging import get_logger
from app.news.models import SentimentLabel

logger = get_logger(__name__)

MODEL_NAME = "ProsusAI/finbert"

_LABEL_MAP = {
    "positive": SentimentLabel.POSITIVE,
    "negative": SentimentLabel.NEGATIVE,
    "neutral": SentimentLabel.NEUTRAL,
}


class SentimentAnalyzer:
    """Lazily loads the FinBERT pipeline on first use, in a background
    thread, so a slow first-time model download never blocks startup or the
    event loop."""

    def __init__(self) -> None:
        self._pipeline: Any = None
        self._load_failed = False
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> bool:
        if self._pipeline is not None:
            return True
        if self._load_failed:
            return False
        with self._lock:
            if self._pipeline is not None:
                return True
            if self._load_failed:
                return False
            try:
                from transformers import pipeline

                logger.info("loading FinBERT sentiment model (first use may download it)...")
                self._pipeline = pipeline("sentiment-analysis", model=MODEL_NAME)
                logger.info("FinBERT sentiment model ready")
                return True
            except Exception:  # noqa: BLE001 - missing/broken ML deps must not break the app
                logger.exception(
                    "sentiment analyzer unavailable (transformers/torch missing or model "
                    "load failed) - news headlines will show without sentiment scoring"
                )
                self._load_failed = True
                return False

    def classify_sync(self, texts: list[str]) -> list[tuple[SentimentLabel, float]]:
        if not texts:
            return []
        if not self._ensure_loaded():
            return [(SentimentLabel.UNAVAILABLE, 0.0)] * len(texts)

        results = self._pipeline(texts, truncation=True)
        return [
            (_LABEL_MAP.get(r["label"].lower(), SentimentLabel.NEUTRAL), float(r["score"]))
            for r in results
        ]

    async def classify(self, texts: list[str]) -> list[tuple[SentimentLabel, float]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.classify_sync, texts)


_analyzer: SentimentAnalyzer | None = None


def get_sentiment_analyzer() -> SentimentAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = SentimentAnalyzer()
    return _analyzer
