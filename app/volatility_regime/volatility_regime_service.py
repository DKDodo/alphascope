"""Periodically recomputes a market's self-contained realized-volatility
risk multiplier from its own benchmark index. Polled on the same slow,
day-scale cadence as DailyTrendService -- a volatility regime doesn't flip
hour to hour.
"""
from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.volatility_regime.models import VolatilityRegime
from app.volatility_regime.volatility_regime_provider import fetch_volatility_regime

logger = get_logger(__name__)


class VolatilityRegimeService:
    def __init__(
        self,
        benchmark_symbol: str,
        poll_interval_seconds: float = 21_600.0,  # 6 hours by default
    ) -> None:
        self._benchmark_symbol = benchmark_symbol
        self._poll_interval = poll_interval_seconds

        self._latest: VolatilityRegime | None = None
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        self._stopping = False
        self._task = asyncio.create_task(self._loop(), name="volatility-regime-service")

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
            except Exception:  # noqa: BLE001 - a cycle failure must not stop the app
                logger.exception("volatility regime cycle failed for %s", self._benchmark_symbol)
            await asyncio.sleep(self._poll_interval)

    async def _run_cycle(self) -> None:
        fetched = await asyncio.to_thread(fetch_volatility_regime, self._benchmark_symbol)
        if fetched is not None:
            self._latest = fetched
            logger.info(
                "volatility regime cycle complete: %s realized_vol=%s%% percentile=%s multiplier=%.2f",
                self._benchmark_symbol, fetched.realized_vol_pct, fetched.percentile_rank, fetched.risk_multiplier,
            )

    def get_risk_multiplier(self) -> float:
        return self._latest.risk_multiplier if self._latest is not None else 1.0
