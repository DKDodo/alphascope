"""Per-symbol rolling market state and indicator computation.

Bars are appended to fixed-size deques (no DataFrame is rebuilt per event),
and indicators are recomputed from that bounded window each cycle — cheap
enough for hundreds/thousands of symbols at 1-minute bar frequency.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from app.indicators.momentum import MacdResult, macd, rsi
from app.indicators.moving_average import ema
from app.indicators.volatility import BollingerBands, atr, bollinger_bands
from app.indicators.volume import momentum as momentum_roc
from app.indicators.volume import volume_ratio, vwap
from app.market_data.models import EventType, MarketEvent

ROLLING_WINDOW = 250


@dataclass
class IndicatorSnapshot:
    symbol: str
    price: float
    ema9: float | None
    ema20: float | None
    ema50: float | None
    ema200: float | None
    rsi14: float | None
    macd: MacdResult | None
    atr14: float | None
    bollinger: BollingerBands | None
    vwap: float | None
    volume_ratio: float | None
    momentum_roc: float | None
    bars_available: int


class SymbolState:
    __slots__ = ("opens", "highs", "lows", "closes", "volumes")

    def __init__(self, maxlen: int = ROLLING_WINDOW) -> None:
        self.opens: deque[float] = deque(maxlen=maxlen)
        self.highs: deque[float] = deque(maxlen=maxlen)
        self.lows: deque[float] = deque(maxlen=maxlen)
        self.closes: deque[float] = deque(maxlen=maxlen)
        self.volumes: deque[float] = deque(maxlen=maxlen)

    def add_bar(self, open_: float, high: float, low: float, close: float, volume: float) -> None:
        self.opens.append(open_)
        self.highs.append(high)
        self.lows.append(low)
        self.closes.append(close)
        self.volumes.append(volume)


class ScannerEngine:
    def __init__(self) -> None:
        self._states: dict[str, SymbolState] = {}

    def on_event(self, event: MarketEvent) -> None:
        if event.event_type is not EventType.BAR:
            return  # MVP is bar-based; tick aggregation can be added later without API changes.
        if event.open is None or event.high is None or event.low is None or event.close is None:
            return
        state = self._states.setdefault(event.symbol, SymbolState())
        state.add_bar(event.open, event.high, event.low, event.close, event.volume or 0.0)

    def seed_bar(
        self, symbol: str, open_: float, high: float, low: float, close: float, volume: float
    ) -> None:
        """Same as on_event, but for warm-starting from persisted history at
        startup rather than a live provider event — see bar_repository.py."""
        state = self._states.setdefault(symbol, SymbolState())
        state.add_bar(open_, high, low, close, volume)

    def has_data(self, symbol: str) -> bool:
        return symbol in self._states and len(self._states[symbol].closes) > 0

    def tracked_symbols(self) -> list[str]:
        return list(self._states.keys())

    def compute_indicators(self, symbol: str) -> IndicatorSnapshot | None:
        state = self._states.get(symbol)
        if state is None or not state.closes:
            return None

        closes = list(state.closes)
        highs = list(state.highs)
        lows = list(state.lows)
        volumes = list(state.volumes)
        price = closes[-1]

        macd_result = macd(closes)

        return IndicatorSnapshot(
            symbol=symbol,
            price=price,
            ema9=ema(closes, 9),
            ema20=ema(closes, 20),
            ema50=ema(closes, 50),
            ema200=ema(closes, 200),
            rsi14=rsi(closes, 14),
            macd=macd_result,
            atr14=atr(highs, lows, closes, 14),
            bollinger=bollinger_bands(closes, 20, 2.0),
            vwap=vwap(highs, lows, closes, volumes),
            volume_ratio=volume_ratio(volumes[-1], volumes[:-1] or volumes, lookback=20),
            momentum_roc=momentum_roc(closes, 10),
            bars_available=len(closes),
        )
