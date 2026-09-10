from __future__ import annotations

import asyncio

import pytest

from app.market_data.models import EventType
from app.market_data.normalizer import normalize_event
from app.market_data.providers.mock_provider import MockProvider, _stable_seed


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


def test_stable_seed_is_a_fixed_crc32_value_not_pythons_randomized_hash():
    # Regression guard for the "deterministic if seeded" claim actually
    # holding ACROSS process restarts, not just within one pytest run: the
    # two calls above always matched even under the old hash()-based code,
    # because Python's str-hash randomization is fixed once per process --
    # the bug only ever showed up as a DIFFERENT sequence after restarting
    # the app. crc32 has no such per-process randomization, so asserting
    # against a hardcoded expected value proves this doesn't route through
    # hash() anymore (a hash()-based value could never reliably match a
    # fixed literal like this).
    assert _stable_seed(42, "AAPL") == 4098019582
    assert _stable_seed(42, "AAPL") == _stable_seed(42, "AAPL")
    assert _stable_seed(42, "AAPL") != _stable_seed(42, "MSFT")
