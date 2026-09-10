"""Per-symbol rolling market state and indicator computation.

Bars are appended to fixed-size deques (no DataFrame is rebuilt per event),
and indicators are recomputed from that bounded window each cycle — cheap
enough for hundreds/thousands of symbols at 1-minute bar frequency.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime

from app.core.logging import get_logger
from app.indicators.momentum import MacdResult, macd, rsi
from app.indicators.moving_average import ema
from app.indicators.volatility import BollingerBands, atr, bollinger_bands
from app.indicators.volume import momentum as momentum_roc
from app.indicators.volume import volume_ratio, vwap
from app.market_data.models import EventType, MarketEvent

logger = get_logger(__name__)

# EMA is mathematically an infinite-memory average, but this deque is
# bounded, so ema()/ema_series() reseeds from whatever bar now sits at the
# start of the window every time it evicts -- at window=250, EMA200 (whose
# natural memory horizon is comparable to the window itself) never fully
# converges to the true infinite-history value. A wider window makes the
# residual bias negligible ((1 - 2/201)^1000 ~= 0.0045%) without the bigger
# architecture change of switching to a stateful/incremental EMA; the other
# indicators (RSI14/ATR14/MACD/Bollinger20) only ever read the tail of this
# window, so widening it doesn't change their output.
ROLLING_WINDOW = 1000


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
    last_bar_time: datetime | None = None


class SymbolState:
    __slots__ = ("opens", "highs", "lows", "closes", "volumes", "timestamps")

    def __init__(self, maxlen: int = ROLLING_WINDOW) -> None:
        self.opens: deque[float] = deque(maxlen=maxlen)
        self.highs: deque[float] = deque(maxlen=maxlen)
        self.lows: deque[float] = deque(maxlen=maxlen)
        self.closes: deque[float] = deque(maxlen=maxlen)
        self.volumes: deque[float] = deque(maxlen=maxlen)
        self.timestamps: deque[datetime | None] = deque(maxlen=maxlen)

    def add_bar(
        self,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        timestamp: datetime | None = None,
    ) -> bool:
        """Appends a new bar, unless it's strictly older than the most
        recent one already on record -- guards against a historical
        (seed_bar) bar landing after a live (on_event) one already did for
        the same symbol, e.g. main.py's cold-start backfill task racing the
        live provider's own stream() task. Without this, closes[-1] (used
        everywhere as "current price") could become a stale historical
        close, and every indicator would compute over an out-of-order
        window for up to ROLLING_WINDOW subsequent bars. Equal timestamps
        still go through unchanged (e.g. a legitimate repeat poll). Returns
        False when rejected, so callers can log it."""
        if (
            timestamp is not None
            and self.timestamps
            and self.timestamps[-1] is not None
            and timestamp < self.timestamps[-1]
        ):
            return False
        self.opens.append(open_)
        self.highs.append(high)
        self.lows.append(low)
        self.closes.append(close)
        self.volumes.append(volume)
        self.timestamps.append(timestamp)
        return True


class ScannerEngine:
    def __init__(self) -> None:
        self._states: dict[str, SymbolState] = {}

    def on_event(self, event: MarketEvent) -> None:
        if event.event_type is not EventType.BAR:
            return  # MVP is bar-based; tick aggregation can be added later without API changes.
        if event.open is None or event.high is None or event.low is None or event.close is None:
            return
        state = self._states.setdefault(event.symbol, SymbolState())
        if not state.add_bar(
            event.open, event.high, event.low, event.close, event.volume or 0.0, event.timestamp
        ):
            logger.warning(
                "out-of-order live bar for %s dropped (older than the last one on record)", event.symbol
            )

    def seed_bar(
        self,
        symbol: str,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        timestamp: datetime | None = None,
    ) -> None:
        """Same as on_event, but for warm-starting from persisted history at
        startup rather than a live provider event — see bar_repository.py."""
        state = self._states.setdefault(symbol, SymbolState())
        if not state.add_bar(open_, high, low, close, volume, timestamp):
            logger.warning(
                "out-of-order seed bar for %s dropped (older than a live bar that already arrived)", symbol
            )

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
        session_highs, session_lows, session_closes, session_volumes = _session_bars(state)

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
            vwap=vwap(session_highs, session_lows, session_closes, session_volumes),
            # volumes[:-1] excludes the current bar from its own baseline --
            # with only one bar ever seen, that's an empty history, and
            # volume_ratio() already returns None for that (not a fake 1.0x
            # "average" comparing the current bar against only itself).
            volume_ratio=volume_ratio(volumes[-1], volumes[:-1], lookback=20),
            momentum_roc=momentum_roc(closes, 10),
            bars_available=len(closes),
            last_bar_time=state.timestamps[-1] if state.timestamps else None,
        )


def _session_bars(state: SymbolState) -> tuple[list[float], list[float], list[float], list[float]]:
    """VWAP is a session-anchored indicator by definition -- restricts the
    rolling window to bars from the same UTC calendar day as the most recent
    bar. Timestamps reaching SymbolState are always tz-aware UTC by the time
    they get here (see MarketEvent/YFinanceProvider and main.py's seeding
    path), and neither a US/BIST trading session nor a UTC day ever crosses
    UTC midnight, so a plain UTC calendar-day filter is exact for those and a
    reasonable, standard convention for 24/7 crypto. Falls back to the full
    window (previous behavior) if no bars from "today" exist yet -- e.g. the
    very first bar of a session -- so VWAP never silently disappears."""
    timestamps = state.timestamps
    highs = list(state.highs)
    lows = list(state.lows)
    closes = list(state.closes)
    volumes = list(state.volumes)
    if not timestamps or timestamps[-1] is None:
        return highs, lows, closes, volumes

    today = timestamps[-1].date()
    idx = [i for i, ts in enumerate(timestamps) if ts is not None and ts.date() == today]
    if not idx:
        return highs, lows, closes, volumes
    return (
        [highs[i] for i in idx],
        [lows[i] for i in idx],
        [closes[i] for i in idx],
        [volumes[i] for i in idx],
    )
