from __future__ import annotations

from app.fundamentals import long_term_scoring
from app.fundamentals.models import FundamentalSnapshot, LongTermOutlookLabel


def _snapshot(**overrides) -> FundamentalSnapshot:
    defaults = dict(
        symbol="TEST", long_name="Test Inc.", sector="Technology",
        trailing_pe=None, forward_pe=None, price_to_book=None,
        profit_margin_pct=None, ebitda_margin_pct=None, revenue_growth_pct=None,
        return_on_equity_pct=None, debt_to_equity=None, analyst_recommendation=None,
        analyst_target_price=None, current_price=100.0,
        market_cap=None, book_value_per_share=None, net_income=None,
    )
    defaults.update(overrides)
    return FundamentalSnapshot(**defaults)


def test_valuation_scores_low_pe_favorably():
    score, reasons = long_term_scoring.score_valuation(_snapshot(trailing_pe=10.0))
    assert score == 14
    assert reasons[0].positive is True


def test_valuation_flags_negative_earnings():
    score, reasons = long_term_scoring.score_valuation(_snapshot(trailing_pe=-5.0))
    assert score == 0
    assert reasons[0].positive is False


def test_valuation_flags_expensive_pe():
    score, reasons = long_term_scoring.score_valuation(_snapshot(trailing_pe=55.0))
    assert score == 0
    assert reasons[0].positive is False


def test_valuation_no_data_returns_no_reasons():
    score, reasons = long_term_scoring.score_valuation(_snapshot())
    assert score == 0
    assert reasons == []


def test_valuation_rewards_low_price_to_book():
    score, reasons = long_term_scoring.score_valuation(_snapshot(price_to_book=0.8))
    assert score == 6
    assert reasons[0].positive is True


def test_valuation_flags_high_price_to_book():
    score, reasons = long_term_scoring.score_valuation(_snapshot(price_to_book=10.0))
    assert score == 0
    assert reasons[0].positive is False


def test_valuation_combines_pe_and_price_to_book():
    score, _ = long_term_scoring.score_valuation(_snapshot(trailing_pe=10.0, price_to_book=0.8))
    assert score == 20


def test_profitability_combines_margin_and_roe():
    score, reasons = long_term_scoring.score_profitability(
        _snapshot(profit_margin_pct=20.0, return_on_equity_pct=25.0)
    )
    assert score == 14
    assert len(reasons) == 2


def test_profitability_combines_all_three_metrics():
    score, reasons = long_term_scoring.score_profitability(
        _snapshot(profit_margin_pct=20.0, ebitda_margin_pct=30.0, return_on_equity_pct=25.0)
    )
    assert score == 20
    assert len(reasons) == 3


def test_profitability_flags_negative_ebitda_margin():
    score, reasons = long_term_scoring.score_profitability(_snapshot(ebitda_margin_pct=-5.0))
    assert score == 0
    assert reasons[0].positive is False


def test_growth_flags_contraction():
    score, reasons = long_term_scoring.score_growth(_snapshot(revenue_growth_pct=-5.0))
    assert score == 0
    assert reasons[0].positive is False


def test_financial_health_flags_high_leverage():
    score, reasons = long_term_scoring.score_financial_health(_snapshot(debt_to_equity=200.0))
    assert score == 0
    assert reasons[0].positive is False


def test_financial_health_rewards_low_debt():
    score, _ = long_term_scoring.score_financial_health(_snapshot(debt_to_equity=30.0))
    assert score == 20


def test_recommendation_and_trend_both_positive():
    score, reasons = long_term_scoring.score_recommendation_and_trend(
        _snapshot(analyst_recommendation="strong_buy"), long_term_trend_up=True
    )
    assert score == 20
    assert all(r.positive for r in reasons)


def test_evaluate_favorable_outlook_end_to_end():
    snapshot = _snapshot(
        trailing_pe=12.0, profit_margin_pct=20.0, return_on_equity_pct=22.0,
        revenue_growth_pct=15.0, debt_to_equity=30.0, analyst_recommendation="buy",
    )
    outlook = long_term_scoring.evaluate_long_term_outlook(snapshot, long_term_trend_up=True)
    assert outlook.label == LongTermOutlookLabel.FAVORABLE
    assert outlook.score >= 65
    assert len(outlook.reasons) > 0


def test_evaluate_unfavorable_outlook_end_to_end():
    snapshot = _snapshot(
        trailing_pe=60.0, profit_margin_pct=-10.0, return_on_equity_pct=-5.0,
        revenue_growth_pct=-8.0, debt_to_equity=250.0, analyst_recommendation="sell",
    )
    outlook = long_term_scoring.evaluate_long_term_outlook(snapshot, long_term_trend_up=False)
    assert outlook.label == LongTermOutlookLabel.UNFAVORABLE
    assert all(r.positive is False for r in outlook.reasons)


def test_evaluate_missing_snapshot_is_insufficient_data():
    outlook = long_term_scoring.evaluate_long_term_outlook(None, long_term_trend_up=None)
    assert outlook.label == LongTermOutlookLabel.INSUFFICIENT_DATA
    assert outlook.score == 0


def test_evaluate_snapshot_with_no_fields_is_insufficient_data():
    outlook = long_term_scoring.evaluate_long_term_outlook(_snapshot(), long_term_trend_up=None)
    assert outlook.label == LongTermOutlookLabel.INSUFFICIENT_DATA
