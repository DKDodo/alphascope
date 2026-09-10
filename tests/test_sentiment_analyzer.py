from __future__ import annotations

import builtins

from app.news.models import SentimentLabel
from app.news.sentiment_analyzer import SentimentAnalyzer


def test_falls_back_to_keyword_when_transformers_unavailable(monkeypatch):
    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "transformers":
            raise ImportError("simulated: transformers not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)

    analyzer = SentimentAnalyzer()
    assert analyzer.method == "unknown"

    results = analyzer.classify_sync(["Company profit surges on strong earnings beat"])

    assert analyzer.method == "keyword"
    assert results[0][0] == SentimentLabel.POSITIVE


def test_empty_input_returns_empty_without_loading_anything():
    analyzer = SentimentAnalyzer()
    assert analyzer.classify_sync([]) == []
    assert analyzer.method == "unknown"  # never attempted a load


def test_batch_failure_falls_back_to_keyword_for_that_call_only():
    # One bad string in a whole market's combined batch (all symbols'
    # headlines go through a single FinBERT call) must not blank out every
    # OTHER symbol's sentiment for the cycle -- it should fall back to the
    # keyword classifier for this batch, same as when FinBERT never loaded.
    analyzer = SentimentAnalyzer()
    analyzer._pipeline = lambda texts, truncation=True: (_ for _ in ()).throw(RuntimeError("boom"))

    results = analyzer.classify_sync(["Company profit surges on strong earnings beat"])

    assert results[0][0] == SentimentLabel.POSITIVE
