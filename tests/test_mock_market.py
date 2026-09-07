from __future__ import annotations

import asyncio

import pytest

from app.market_data.models import EventType
from app.market_data.normalizer import normalize_event
from app.market_data.providers.mock_provider import MockProvider


@pytest.mark.asyncio
async def test_mock_provider_connect_disconnect_lifecycle():
    provider = MockProvider(symbols=["AAPL"], seed=1)
    assert not provider.is_connected
    await provider.connect()
    assert provider.is_connected
    await provider.disconnect()
    assert not provider.is_connected


@pytest.mark.asyncio
async def test_mock_provider_subscribe_unsubscribe():
    provider = MockProvider(symbols=["AAPL", "MSFT"], seed=1)
    await provider.connect()
    await provider.subscribe(["AAPL", "MSFT"])
    await provider.unsubscribe(["MSFT"])

    await provider.subscribe(["AAPL"])
    stream = provider.stream()
    event = await stream.asend(None)
    assert event["symbol"] == "AAPL"
    await provider.disconnect()


@pytest.mark.asyncio
async def test_mock_provider_produces_normalizable_bar_events():
    provider = MockProvider(symbols=["NVDA"], seed=7)
    await provider.connect()
    await provider.subscribe(["NVDA"])

    stream = provider.stream()
    raw_event = await stream.asend(None)

    assert raw_event["event_type"] == EventType.BAR
    normalized = normalize_event("mock", raw_event)
    assert normalized.symbol == "NVDA"
    assert normalized.close is not None
    assert normalized.event_type == EventType.BAR
    await provider.disconnect()


@pytest.mark.asyncio
async def test_mock_provider_is_deterministic_with_same_seed():
    async def first_bar(seed: int) -> float:
        provider = MockProvider(symbols=["AAPL"], seed=seed, tick_interval_seconds=0.01)
        await provider.connect()
        await provider.subscribe(["AAPL"])
        stream = provider.stream()
        event = await stream.asend(None)
        await provider.disconnect()
        return event["close"]

    price_a, price_b = await asyncio.gather(first_bar(99), first_bar(99))
    assert price_a == price_b
