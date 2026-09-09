from __future__ import annotations

import json

import pytest

from app.market_data.models import AssetClass, EventType
from app.market_data.normalizer import normalize_event
from app.market_data.providers.binance_provider import BinanceProvider


def _kline_message(
    stream: str = "btcusdt@kline_1m",
    pair: str = "BTCUSDT",
    closed: bool = True,
    open_time_ms: int = 1_700_000_000_000,
    close_time_ms: int = 1_700_000_059_999,
    o: str = "60000.00",
    h: str = "60100.00",
    l: str = "59950.00",
    c: str = "60050.50",
    v: str = "12.345",
) -> dict:
    return {
        "stream": stream,
        "data": {
            "e": "kline",
            "E": close_time_ms,
            "s": pair,
            "k": {
                "t": open_time_ms,
                "T": close_time_ms,
                "s": pair,
                "i": "1m",
                "o": o,
                "h": h,
                "l": l,
                "c": c,
                "v": v,
                "x": closed,
            },
        },
    }


_PAIR_MAP = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}


def test_parse_kline_message_returns_none_when_still_forming():
    message = _kline_message(closed=False)

    result = BinanceProvider._parse_kline_message(message, _PAIR_MAP, "CRYPTO")

    assert result is None


def test_parse_kline_message_returns_bar_when_closed():
    message = _kline_message(closed=True)

    result = BinanceProvider._parse_kline_message(message, _PAIR_MAP, "CRYPTO")

    assert result is not None
    assert result["symbol"] == "BTC"
    assert result["asset_class"] == AssetClass.CRYPTO
    assert result["exchange"] == "CRYPTO"
    assert result["event_type"] == EventType.BAR
    assert result["open"] == 60000.00
    assert result["high"] == 60100.00
    assert result["low"] == 59950.00
    assert result["close"] == 60050.50
    assert result["volume"] == 12.345


def test_parse_kline_message_uses_close_time_not_start_time():
    message = _kline_message(open_time_ms=1_700_000_000_000, close_time_ms=1_700_000_059_999)

    result = BinanceProvider._parse_kline_message(message, _PAIR_MAP, "CRYPTO")

    assert result["timestamp"].timestamp() == pytest.approx(1_700_000_059_999 / 1000)


def test_parse_kline_message_multi_symbol_combined_stream_payload():
    btc_msg = _kline_message(stream="btcusdt@kline_1m", pair="BTCUSDT", c="61000")
    eth_msg = _kline_message(stream="ethusdt@kline_1m", pair="ETHUSDT", c="3000")

    btc_result = BinanceProvider._parse_kline_message(btc_msg, _PAIR_MAP, "CRYPTO")
    eth_result = BinanceProvider._parse_kline_message(eth_msg, _PAIR_MAP, "CRYPTO")

    assert btc_result["symbol"] == "BTC"
    assert btc_result["close"] == 61000.0
    assert eth_result["symbol"] == "ETH"
    assert eth_result["close"] == 3000.0


def test_parse_kline_message_unrecognized_pair_returns_none():
    message = _kline_message(pair="DOGEUSDT")

    result = BinanceProvider._parse_kline_message(message, _PAIR_MAP, "CRYPTO")

    assert result is None


def test_parse_kline_message_subscribe_ack_returns_none():
    # {"result": null, "id": 1} -- what Binance sends back to confirm a
    # SUBSCRIBE/UNSUBSCRIBE request, not a kline at all.
    ack = {"result": None, "id": 1}

    result = BinanceProvider._parse_kline_message(ack, _PAIR_MAP, "CRYPTO")

    assert result is None


@pytest.mark.parametrize(
    "message",
    [
        "not a dict",
        {},
        {"data": "not a dict"},
        {"data": {}},
        {"data": {"k": "not a dict"}},
        {"data": {"k": {"x": True}}},  # missing o/h/l/c/v/T/s
        {"data": {"k": {"x": True, "s": "BTCUSDT", "T": 1, "o": "bad", "h": "1", "l": "1", "c": "1", "v": "1"}}},
    ],
)
def test_parse_kline_message_malformed_payload_returns_none_not_raise(message):
    result = BinanceProvider._parse_kline_message(message, _PAIR_MAP, "CRYPTO")

    assert result is None


def test_parse_kline_message_normalizes_like_yfinance_shape():
    message = _kline_message(closed=True)
    raw = BinanceProvider._parse_kline_message(message, _PAIR_MAP, "CRYPTO")

    event = normalize_event("binance", raw)

    assert event.symbol == "BTC"
    assert event.asset_class == AssetClass.CRYPTO
    assert event.exchange == "CRYPTO"
    assert event.event_type == EventType.BAR
    assert event.close == 60050.50
    assert event.price == 60050.50


def test_to_binance_pair_uppercases_and_concatenates():
    assert BinanceProvider.to_binance_pair("btc", "usdt") == "BTCUSDT"
    assert BinanceProvider.to_binance_pair("ETH", "USDT") == "ETHUSDT"


class _FakeWebSocket:
    def __init__(self, incoming: list[str] | None = None, fail_on_iter: bool = False):
        self.sent: list[str] = []
        self._incoming = list(incoming or [])
        self._fail_on_iter = fail_on_iter
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._fail_on_iter:
            raise ConnectionError("simulated drop")
        if not self._incoming:
            raise StopAsyncIteration
        return self._incoming.pop(0)


@pytest.mark.asyncio
async def test_connect_opens_websocket(monkeypatch):
    fake_ws = _FakeWebSocket()

    async def fake_connect(url, *args, **kwargs):
        return fake_ws

    monkeypatch.setattr(
        "app.market_data.providers.binance_provider.websockets.connect", fake_connect
    )

    provider = BinanceProvider(symbols=["BTC"])
    await provider.connect()

    assert provider.is_connected
    assert provider._ws is fake_ws


@pytest.mark.asyncio
async def test_subscribe_sends_subscribe_message_for_all_symbols(monkeypatch):
    fake_ws = _FakeWebSocket()

    async def fake_connect(url, *args, **kwargs):
        return fake_ws

    monkeypatch.setattr(
        "app.market_data.providers.binance_provider.websockets.connect", fake_connect
    )

    provider = BinanceProvider(symbols=["BTC", "ETH"])
    await provider.connect()
    await provider.subscribe(["BTC", "ETH"])

    assert len(fake_ws.sent) == 1
    payload = json.loads(fake_ws.sent[0])
    assert payload["method"] == "SUBSCRIBE"
    assert set(payload["params"]) == {"btcusdt@kline_1m", "ethusdt@kline_1m"}


@pytest.mark.asyncio
async def test_unsubscribe_sends_unsubscribe_message(monkeypatch):
    fake_ws = _FakeWebSocket()

    async def fake_connect(url, *args, **kwargs):
        return fake_ws

    monkeypatch.setattr(
        "app.market_data.providers.binance_provider.websockets.connect", fake_connect
    )

    provider = BinanceProvider(symbols=["BTC"])
    await provider.connect()
    await provider.subscribe(["BTC"])
    await provider.unsubscribe(["BTC"])

    assert provider._subscribed == set()
    payload = json.loads(fake_ws.sent[-1])
    assert payload["method"] == "UNSUBSCRIBE"
    assert payload["params"] == ["btcusdt@kline_1m"]


@pytest.mark.asyncio
async def test_stream_yields_parsed_events_from_closed_klines(monkeypatch):
    raw_message = json.dumps(_kline_message(closed=True))
    fake_ws = _FakeWebSocket(incoming=[raw_message])

    async def fake_connect(url, *args, **kwargs):
        return fake_ws

    monkeypatch.setattr(
        "app.market_data.providers.binance_provider.websockets.connect", fake_connect
    )

    provider = BinanceProvider(symbols=["BTC"])
    await provider.connect()
    await provider.subscribe(["BTC"])

    # stream() is an infinite generator (mirrors a real live feed) -- pull
    # just the one event this fake socket has, never fully consume it.
    event = await anext(provider.stream())

    assert event["symbol"] == "BTC"


@pytest.mark.asyncio
async def test_stream_drops_still_forming_updates(monkeypatch):
    forming = json.dumps(_kline_message(closed=False))
    closed = json.dumps(_kline_message(closed=True))
    fake_ws = _FakeWebSocket(incoming=[forming, forming, closed])

    async def fake_connect(url, *args, **kwargs):
        return fake_ws

    monkeypatch.setattr(
        "app.market_data.providers.binance_provider.websockets.connect", fake_connect
    )

    provider = BinanceProvider(symbols=["BTC"])
    await provider.connect()
    await provider.subscribe(["BTC"])

    # The two forming updates are silently skipped inside the generator;
    # the first value anext() produces is the closed kline.
    event = await anext(provider.stream())

    assert event["symbol"] == "BTC"


@pytest.mark.asyncio
async def test_stream_reconnects_after_dropped_connection(monkeypatch):
    dying_ws = _FakeWebSocket(fail_on_iter=True)
    healthy_ws = _FakeWebSocket(incoming=[json.dumps(_kline_message(closed=True))])
    connect_calls = []

    async def fake_connect(url, *args, **kwargs):
        connect_calls.append(url)
        return dying_ws if len(connect_calls) == 1 else healthy_ws

    monkeypatch.setattr(
        "app.market_data.providers.binance_provider.websockets.connect", fake_connect
    )

    provider = BinanceProvider(symbols=["BTC"], max_reconnect_backoff_seconds=0.01)
    await provider.connect()
    await provider.subscribe(["BTC"])

    # First iteration attempt dies immediately (fail_on_iter=True), triggering
    # the reconnect-with-backoff path (a real ~1s sleep, per the initial
    # backoff value -- deliberately not mocked out, to keep this test honest
    # about what the real code path does). The second connect() succeeds and
    # yields the one real event queued on the healthy socket.
    first_event = await anext(provider.stream())

    assert first_event["symbol"] == "BTC"
    assert len(connect_calls) == 2  # first (dying) + reconnect (healthy)
