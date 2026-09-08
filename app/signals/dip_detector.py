"""Mean-reversion ("bought the dip") detection — deliberately separate from
app/signals/scoring.py's trend-following Opportunity Score. See
DipOpportunity's docstring in models.py for why these are never merged into
one number: an oversold bounce candidate can be a textbook AVOID by trend
rules at the very same time, and that's a real, useful distinction to keep
visible rather than average away.

Detection requires ALL of: RSI oversold, price at/near the lower Bollinger
band (a statistically cheap level), and some volume behind it (a silent
drift to a low is a much weaker case than one with participation behind
it). These are common-sense heuristics, not a backtested strategy — see
long_term_scoring.py's docstring for the same caveat applied there.
"""
from __future__ import annotations

from app.scanner.scanner_engine import IndicatorSnapshot
from app.signals.models import DipConfidence, DipOpportunity, Reason

_RSI_OVERSOLD_THRESHOLD = 30.0
_SUPPORT_BAND_TOLERANCE = 1.02  # at or up to 2% above the lower Bollinger band
_VOLUME_CONFIRMATION_RATIO = 1.2
_VOLUME_STRONG_RATIO = 2.0


def detect_dip_opportunity(ind: IndicatorSnapshot) -> DipOpportunity | None:
    if ind.rsi14 is None or ind.bollinger is None or ind.volume_ratio is None:
        return None

    is_oversold = ind.rsi14 < _RSI_OVERSOLD_THRESHOLD
    near_support = ind.price <= ind.bollinger.lower * _SUPPORT_BAND_TOLERANCE
    if not (is_oversold and near_support):
        return None

    reasons = [
        Reason(
            text=f"RSI aşırı satım bölgesinde ({ind.rsi14:.1f}) — düşüş baskısı ekstrem seviyede",
            positive=True,
        ),
        Reason(
            text="Fiyat alt Bollinger bandına yakın/altında — istatistiksel olarak ucuz bölge",
            positive=True,
        ),
    ]

    volume_confirms = ind.volume_ratio > _VOLUME_CONFIRMATION_RATIO
    if volume_confirms:
        reasons.append(
            Reason(
                text=f"Hacim ortalamanın {ind.volume_ratio:.1f} katı — tepki/kapitülasyon işareti olabilir",
                positive=True,
            )
        )
        confidence = (
            DipConfidence.STRONG if ind.volume_ratio > _VOLUME_STRONG_RATIO else DipConfidence.MEDIUM
        )
    else:
        reasons.append(
            Reason(
                text=f"Hacim düşük ({ind.volume_ratio:.1f}x) — henüz teyit yok, dikkatli olun",
                positive=False,
            )
        )
        confidence = DipConfidence.WEAK

    return DipOpportunity(confidence=confidence, reasons=reasons)
