from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd

from app.volatility_regime.volatility_regime_provider import (
    ELEVATED_MULTIPLIER,
    HIGH_MULTIPLIER,
    MIN_WARMUP_DAYS,
    REALIZED_VOL_WINDOW_DAYS,
    _parse_download,
    multiplier_series_by_date,
)
from app.volatility_regime.volatility_regime_service import VolatilityRegimeService


def _calm_then_stormy_series(calm_days: int = 150, stormy_days: int = 29) -> tuple[list[date], list[float]]:
    """A run of small, steady alternating returns (nothing unusual) followed
    by a run of much larger swings -- the storm should classify as elevated/
    high relative to the calm history that came before it, and the calm
    stretch itself (once past warmup) should not."""
    dates = [date(2022, 1, 1) + timedelta(days=i) for i in range(calm_days + stormy_days + 1)]
    closes = [100.0]
    for i in range(calm_days):
        step = 0.002 if i % 2 == 0 else -0.0015
        closes.append(closes[-1] * (1 + step))
    for i in range(stormy_days):
        step = 0.05 if i % 2 == 0 else -0.045
        closes.append(closes[-1] * (1 + step))
    return dates, closes


def test_multiplier_series_by_date_derates_a_real_volatility_spike():
    dates, closes = _calm_then_stormy_series()

    result = multiplier_series_by_date(dates, closes)

    calm_day = dates[100]  # well past warmup, still in the calm stretch
    assert result.get(calm_day, 1.0) == 1.0

    storm_day = dates[-1]  # deep enough into the storm that the whole 20d window is stormy
    assert result[storm_day] in (ELEVATED_MULTIPLIER, HIGH_MULTIPLIER)


def test_multiplier_series_by_date_empty_below_the_combined_warmup_requirement():
    n = REALIZED_VOL_WINDOW_DAYS + MIN_WARMUP_DAYS - 5
    dates = [date(2022, 1, 1) + timedelta(days=i) for i in range(n)]
    closes = [100.0 + i * 0.1 for i in range(n)]

    assert multiplier_series_by_date(dates, closes) == {}


def test_multiplier_series_by_date_never_uses_a_future_bar():
    # Two otherwise-identical calm-then-stormy series that diverge only
    # AFTER a given cutoff date -- the multiplier assigned to dates at or
    # before the cutoff must be identical whether or not the future storm
    # is present in the input at all (lookahead-bias check).
    dates, calm_closes = _calm_then_stormy_series(calm_days=150, stormy_days=0)
    _, full_closes = _calm_then_stormy_series(calm_days=150, stormy_days=29)

    calm_only_result = multiplier_series_by_date(dates, calm_closes)
    full_result = multiplier_series_by_date(dates[: len(calm_closes)], full_closes[: len(calm_closes)])

    assert calm_only_result == full_result


def _daily_frame(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2022-01-01", periods=len(closes), freq="1D")
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": [1000.0] * len(closes)}, index=idx)


def test_parse_download_single_ticker_is_multiindexed_like_real_yfinance():
    """Same real-yfinance quirk already found and fixed in
    daily_trend_provider.py/historical_data.py: a single-ticker
    yf.download() can still come back MultiIndex-columned."""
    _, closes = _calm_then_stormy_series()
    data = pd.concat({"XU100.IS": _daily_frame(closes)}, axis=1)

    result = _parse_download("XU100.IS", data, datetime.now(timezone.utc))

    assert result is not None
    assert result.risk_multiplier in (1.0, ELEVATED_MULTIPLIER, HIGH_MULTIPLIER)


def test_parse_download_empty_frame_returns_none():
    result = _parse_download("XU100.IS", pd.DataFrame(), datetime.now(timezone.utc))

    assert result is None


def test_volatility_regime_service_defaults_to_no_derating_before_first_poll():
    service = VolatilityRegimeService(benchmark_symbol="XU100.IS")
    assert service.get_risk_multiplier() == 1.0
