"""ATR-based stop/target and risk-level analysis. No order execution — analysis only."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from app.core.exceptions import RiskCalculationError

DEFAULT_STOP_ATR_MULTIPLIER = 1.5
DEFAULT_TP1_ATR_MULTIPLIER = 2.0
DEFAULT_TP2_ATR_MULTIPLIER = 3.5


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RiskAnalysis(BaseModel):
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    atr: float
    risk_per_share: float
    reward_per_share_tp1: float
    risk_reward_ratio: float
    risk_level: RiskLevel


class RiskEngine:
    def __init__(
        self,
        stop_atr_multiplier: float = DEFAULT_STOP_ATR_MULTIPLIER,
        tp1_atr_multiplier: float = DEFAULT_TP1_ATR_MULTIPLIER,
        tp2_atr_multiplier: float = DEFAULT_TP2_ATR_MULTIPLIER,
    ) -> None:
        self._stop_mult = stop_atr_multiplier
        self._tp1_mult = tp1_atr_multiplier
        self._tp2_mult = tp2_atr_multiplier

    def analyze(
        self, entry_price: float, atr: float, resistance_price: float | None = None
    ) -> RiskAnalysis:
        if entry_price <= 0:
            raise RiskCalculationError("entry_price must be positive")
        if atr <= 0:
            raise RiskCalculationError("atr must be positive")

        stop_loss = entry_price - atr * self._stop_mult

        # Anchor TP1 to real market structure (e.g. the upper Bollinger band)
        # when available, with a minimum ATR-based floor so a resistance
        # level sitting right on top of price never produces a near-zero
        # target. Without a structure price (the ratio between two fixed
        # ATR multiples is a constant regardless of symbol or market
        # conditions — it never actually distinguishes a good setup from a
        # bad one) falls back to the plain ATR multiple.
        atr_based_tp1 = entry_price + atr * self._tp1_mult
        if resistance_price is not None and resistance_price > entry_price:
            take_profit_1 = max(resistance_price, entry_price + atr * 0.5)
        else:
            take_profit_1 = atr_based_tp1

        # From the clamped stop_loss (below), not the pre-clamp local --
        # otherwise a stop distance wide enough to clamp to 0 would still
        # report the pre-clamp (negative) distance here, so risk_per_share
        # and risk_reward_ratio wouldn't reconcile with the stop_loss this
        # response actually shows.
        risk_per_share = entry_price - max(stop_loss, 0.0)
        reward_per_share_tp1 = take_profit_1 - entry_price
        # TP2 keeps the same reward-multiple relative to TP1 that the pure
        # ATR-based fallback would have had (tp2_mult / tp1_mult), so a
        # structure-anchored TP1 still implies a proportionally further TP2.
        take_profit_2 = entry_price + reward_per_share_tp1 * (self._tp2_mult / self._tp1_mult)

        risk_reward_ratio = reward_per_share_tp1 / risk_per_share if risk_per_share > 0 else 0.0

        atr_pct = atr / entry_price * 100.0
        risk_level = self._classify_risk_level(atr_pct)

        return RiskAnalysis(
            entry_price=round(entry_price, 4),
            stop_loss=round(max(stop_loss, 0.0), 4),
            take_profit_1=round(take_profit_1, 4),
            take_profit_2=round(take_profit_2, 4),
            atr=round(atr, 4),
            risk_per_share=round(risk_per_share, 4),
            reward_per_share_tp1=round(reward_per_share_tp1, 4),
            risk_reward_ratio=round(risk_reward_ratio, 2),
            risk_level=risk_level,
        )

    @staticmethod
    def _classify_risk_level(atr_pct: float) -> RiskLevel:
        if atr_pct < 1.5:
            return RiskLevel.LOW
        if atr_pct < 3.5:
            return RiskLevel.MEDIUM
        return RiskLevel.HIGH
