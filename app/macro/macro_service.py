"""Periodically refreshes a small, fixed set of macro indicators for one
market. Polled on a slow interval — FX/index levels are context, not
something a scanner needs tick-fresh."""
from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.macro.macro_provider import fetch_macro_indicator
from app.macro.models import MacroIndicator

logger = get_logger(__name__)


class MacroService:
    def __init__(
        self,
        indicators: list[tuple[str, str, str]],  # (symbol, label, description)
        poll_interval_seconds: float = 300.0,
        day_reset_symbols: frozenset[str] = frozenset(),
    ) -> None:
        self._indicators = indicators
        self._poll_interval = poll_interval_seconds
        # Symbols in here get a change % measured from today's 00:00 Turkey
        # time instead of the previous daily close — for 24/7 assets (crypto)
        # that have no exchange session to anchor a "previous close" to.
        self._day_reset_symbols = day_reset_symbols
        self._latest: list[MacroIndicator] = []
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        self._stopping = False
        self._task = asyncio.create_task(self._loop(), name="macro-service")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self._run_cycle()
            except Exception:  # noqa: BLE001 - a macro cycle failure must not stop the app
                logger.exception("macro cycle failed")
            await asyncio.sleep(self._poll_interval)

    async def _run_cycle(self) -> None:
        results = await asyncio.gather(
            *[
                fetch_macro_indicator(
                    symbol, label, desc, day_reset=symbol in self._day_reset_symbols
                )
                for symbol, label, desc in self._indicators
            ]
        )
        fetched = [r for r in results if r is not None]
        if fetched:
            self._latest = fetched
            logger.info("macro cycle complete: %d/%d indicators", len(fetched), len(self._indicators))

    def get_indicators(self) -> list[MacroIndicator]:
        return list(self._latest)
