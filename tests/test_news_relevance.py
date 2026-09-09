from __future__ import annotations

from app.news.models import NewsItem, SentimentLabel, SymbolNewsSummary
from app.news.relevance import evaluate_relevant_sentiment


def _item(title: str, sentiment: SentimentLabel) -> NewsItem:
    return NewsItem(title=title, sentiment=sentiment)


def _summary(symbol: str, items: list[NewsItem]) -> SymbolNewsSummary:
    positive = sum(1 for i in items if i.sentiment == SentimentLabel.POSITIVE)
    negative = sum(1 for i in items if i.sentiment == SentimentLabel.NEGATIVE)
    neutral = sum(1 for i in items if i.sentiment == SentimentLabel.NEUTRAL)
    overall = (
        SentimentLabel.UNAVAILABLE if not items
        else SentimentLabel.NEGATIVE if negative > positive and negative >= neutral
        else SentimentLabel.POSITIVE if positive > negative and positive >= neutral
        else SentimentLabel.NEUTRAL
    )
    return SymbolNewsSummary(
        symbol=symbol, items=items, positive_count=positive,
        negative_count=negative, neutral_count=neutral, overall=overall,
    )


def test_headline_mentioning_company_by_alias_counts_as_relevant():
    summary = _summary("BA", [_item("Boeing Trails Airbus in August Deliveries", SentimentLabel.NEGATIVE)])

    verdict = evaluate_relevant_sentiment(summary, "BA")

    assert verdict.alias_filtered is True
    assert verdict.relevant_count == 1
    assert verdict.overall == SentimentLabel.NEGATIVE


def test_headline_not_mentioning_company_is_excluded():
    summary = _summary("BA", [
        _item("Amazon Prime Air Cargo Plane Crashes at Miami Airport", SentimentLabel.NEGATIVE),
        _item("Boeing Rises Even as August Deliveries Fall", SentimentLabel.NEGATIVE),
    ])

    verdict = evaluate_relevant_sentiment(summary, "BA")

    assert verdict.relevant_count == 1  # only the headline naming Boeing counts
    assert verdict.total_count == 2


def test_matching_is_case_insensitive():
    summary = _summary("AAPL", [_item("apple unveils new iphone lineup", SentimentLabel.POSITIVE)])

    verdict = evaluate_relevant_sentiment(summary, "AAPL")

    assert verdict.relevant_count == 1


def test_word_boundary_prevents_partial_word_match():
    # "Metaverse" must NOT count as a Meta Platforms (META) mention.
    summary = _summary("META", [_item("Startup unveils new metaverse platform", SentimentLabel.NEGATIVE)])

    verdict = evaluate_relevant_sentiment(summary, "META")

    assert verdict.relevant_count == 0
    assert verdict.overall == SentimentLabel.UNAVAILABLE


def test_symbol_missing_from_alias_map_falls_back_to_unfiltered_summary():
    summary = _summary("ZZZZ", [_item("Some headline about anything", SentimentLabel.NEGATIVE)])

    verdict = evaluate_relevant_sentiment(summary, "ZZZZ")

    assert verdict.alias_filtered is False
    assert verdict.overall == summary.overall  # echoes _summarize()'s own verdict, unfiltered
    assert verdict.relevant_count == len(summary.items)


def test_all_relevant_headlines_filtered_out_reads_as_unavailable():
    summary = _summary("BA", [
        _item("Dow Jones Futures Fall As Oil Prices Rise", SentimentLabel.NEGATIVE),
        _item("Sector Update: Consumer Stocks Decline", SentimentLabel.NEGATIVE),
    ])

    verdict = evaluate_relevant_sentiment(summary, "BA")

    assert verdict.relevant_count == 0
    assert verdict.overall == SentimentLabel.UNAVAILABLE


def test_none_summary_returns_unavailable_verdict():
    verdict = evaluate_relevant_sentiment(None, "AAPL")

    assert verdict.overall == SentimentLabel.UNAVAILABLE
    assert verdict.alias_filtered is False
    assert verdict.relevant_count == 0


def test_majority_vote_recomputed_from_relevant_subset_only():
    # Two irrelevant NEGATIVE headlines would flip the unfiltered summary's
    # own overall to NEGATIVE, but the relevant subset here is all POSITIVE.
    summary = _summary("BA", [
        _item("Dow Jones Futures Fall As Oil Prices Rise", SentimentLabel.NEGATIVE),
        _item("Sector Update: Consumer Stocks Decline", SentimentLabel.NEGATIVE),
        _item("Boeing Wins Major New Order From Airline", SentimentLabel.POSITIVE),
    ])
    assert summary.overall == SentimentLabel.NEGATIVE  # sanity check on the unfiltered baseline

    verdict = evaluate_relevant_sentiment(summary, "BA")

    assert verdict.relevant_count == 1
    assert verdict.overall == SentimentLabel.POSITIVE
