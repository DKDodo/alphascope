from __future__ import annotations

from app.news.keyword_sentiment import classify_keyword_sync
from app.news.models import SentimentLabel


def test_classifies_clearly_positive_headline():
    label, score = classify_keyword_sync("Company profit rose sharply as shares surge on record earnings beat")
    assert label == SentimentLabel.POSITIVE
    assert score > 0


def test_classifies_clearly_negative_headline():
    label, score = classify_keyword_sync("Company plunges after lawsuit and bankruptcy warning, shares crash")
    assert label == SentimentLabel.NEGATIVE
    assert score > 0


def test_classifies_neutral_headline_with_no_keywords():
    label, score = classify_keyword_sync("Company to hold its annual shareholder meeting next month")
    assert label == SentimentLabel.NEUTRAL


def test_mixed_signals_net_out():
    # one positive phrase, one negative phrase -> net zero -> neutral
    label, _ = classify_keyword_sync("Company beats estimates but warns of headwinds ahead")
    assert label == SentimentLabel.NEUTRAL


def test_never_raises_on_empty_string():
    label, score = classify_keyword_sync("")
    assert label == SentimentLabel.NEUTRAL
    assert score == 0.3
