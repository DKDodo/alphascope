"""Normalized market data models shared by every provider and every consumer."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class AssetClass(str, Enum):
    EQUITY = "EQUITY"
    CRYPTO = "CRYPTO"
    FOREX = "FOREX"
    FUTURES = "FUTURES"
    INDEX = "INDEX"


class EventType(str, Enum):
    TRADE = "TRADE"
    QUOTE = "QUOTE"
    BAR = "BAR"


class MarketEvent(BaseModel):
    """Provider-agnostic market data event.

    Raw provider payloads are never passed downstream directly — they are
    always converted into this shape first (see market_data.normalizer).
    """

    symbol: str
    asset_class: AssetClass = AssetClass.EQUITY
    exchange: str = "UNKNOWN"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: EventType

    price: float | None = None
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    volume: float | None = None

    # Populated for EventType.BAR (1-minute OHLCV bar) — the scanner's
    # primary input, since the MVP is bar-based rather than tick-based.
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
