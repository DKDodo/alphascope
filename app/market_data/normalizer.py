"""Converts provider-native raw payloads into the normalized MarketEvent model."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.exceptions import UnknownProviderError
from app.market_data.models import AssetClass, EventType, MarketEvent


def _normalize_bar_payload(raw: dict[str, Any]) -> MarketEvent:
    """Shared shape for providers that already emit normalized-looking OHLCV
    bar dicts (mock and yfinance both build their raw payloads this way)."""
    return MarketEvent(
        symbol=raw["symbol"],
        asset_class=AssetClass(raw.get("asset_class", AssetClass.EQUITY)),
        exchange=raw.get("exchange", "MOCK"),
        timestamp=raw.get("timestamp", datetime.now(timezone.utc)),
        event_type=EventType(raw["event_type"]),
        price=raw.get("close"),
        volume=raw.get("volume"),
        open=raw.get("open"),
        high=raw.get("high"),
        low=raw.get("low"),
        close=raw.get("close"),
    )


def _normalize_massive(raw: dict[str, Any]) -> MarketEvent:
    """Placeholder mapping for the Massive WebSocket schema.

    Field names follow Massive's documented trade/quote/bar payloads; adjust
    once real payload samples are available. Kept isolated here so the rest
    of the system is unaffected by Massive-specific quirks.
    """
    event_type = EventType(raw.get("type", "TRADE").upper())
    return MarketEvent(
        symbol=raw["sym"],
        asset_class=AssetClass(raw.get("asset_class", AssetClass.EQUITY)),
        exchange=raw.get("exchange", "MASSIVE"),
        timestamp=raw.get("timestamp", datetime.now(timezone.utc)),
        event_type=event_type,
        price=raw.get("price"),
        bid=raw.get("bid"),
        ask=raw.get("ask"),
        bid_size=raw.get("bid_size"),
        ask_size=raw.get("ask_size"),
        volume=raw.get("volume"),
        open=raw.get("open"),
        high=raw.get("high"),
        low=raw.get("low"),
        close=raw.get("close"),
    )


_NORMALIZERS = {
    "mock": _normalize_bar_payload,
    "yfinance": _normalize_bar_payload,
    "massive": _normalize_massive,
    "binance": _normalize_bar_payload,
}


def normalize_event(provider_name: str, raw: dict[str, Any]) -> MarketEvent:
    try:
        normalizer = _NORMALIZERS[provider_name]
    except KeyError as exc:
        raise UnknownProviderError(f"No normalizer registered for provider '{provider_name}'") from exc
    return normalizer(raw)
