"""Periodically fetches and caches fundamental data for every symbol in a
market's universe. Polled far less often than prices/news — company
fundamentals (P/E, margins, growth) move on a quarterly-earnings timescale,
not a minute-to-minute one."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.core.logging import get_logger
from app.fundamentals.fundamentals_provider import fetch_fundamental_snapshot
from app.fundamentals.long_term_scoring import evaluate_long_term_outlook
from app.fundamentals.models import FundamentalSnapshot, LongTermOutlook
from app.scanner.scanner_engine import ScannerEngine

logger = get_logger(__name__)

# Fundamentals move on a quarterly-earnings timescale (see module docstring),
# so this is a generous cutoff, not a tight one -- it exists only to stop a
# symbol that succeeded once and then failed every cycle since (a real
# pattern: Yahoo's quoteSummary endpoint intermittently blocks some hosting
# IPs, see likely_blocked below) from serving a months-old snapshot forever.
_MAX_SNAPSHOT_AGE = timedelta(days=14)


class FundamentalsService:
    def __init__(
        self,
        symbols: list[str],
        scanner_engine: ScannerEngine,
        ticker_suffix: str = "",
        poll_interval_seconds: float = 21_600.0,  # 6 hours by default
    ) -> None:
        self._symbols = symbols
        self._scanner_engine = scanner_engine
        self._ticker_suffix = ticker_suffix
        self._poll_interval = poll_interval_seconds

        self._latest: dict[str, FundamentalSnapshot] = {}
        self._fetched_at: dict[str, datetime] = {}
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._cycles_run = 0

    async def start(self) -> None:
        self._stopping = False
        self._task = asyncio.create_task(self._loop(), name="fundamentals-service")

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
            except Exception:  # noqa: BLE001 - a fundamentals cycle failure must not stop the app
                logger.exception("fundamentals cycle failed")
            await asyncio.sleep(self._poll_interval)

    async def _run_cycle(self) -> None:
        snapshots = await asyncio.gather(
            *[fetch_fundamental_snapshot(symbol, self._ticker_suffix) for symbol in self._symbols]
        )
        found = 0
        now = datetime.now(timezone.utc)
        for symbol, snapshot in zip(self._symbols, snapshots):
            if snapshot is not None:
                self._latest[symbol] = snapshot
                self._fetched_at[symbol] = now
                found += 1
        self._cycles_run += 1
        logger.info("fundamentals cycle complete: %d/%d symbols", found, len(self._symbols))

    @property
    def likely_blocked(self) -> bool:
        """True once we've genuinely tried (a few full cycles) and gotten
        nothing back for any symbol — distinguishes 'data hasn't arrived
        yet' from 'this data source doesn't work from this host' (observed
        in production: Yahoo's quoteSummary endpoint that fundamentals data
        comes from blocks some cloud-hosting IPs, while the price-only
        endpoints the rest of the app uses do not)."""
        return self._cycles_run >= 1 and not self._latest

    def _fresh_snapshot(self, symbol: str) -> FundamentalSnapshot | None:
        fetched_at = self._fetched_at.get(symbol)
        if fetched_at is None or datetime.now(timezone.utc) - fetched_at > _MAX_SNAPSHOT_AGE:
            return None
        return self._latest.get(symbol)

    def get_sector(self, symbol: str) -> str | None:
        """Cheap sector lookup straight from the cache -- unlike
        get_long_term_outlook(), this doesn't trigger a full long-term
        scoring pass, so it's safe to call once per AutoTrader candidate on
        every tick (see AutoTraderService's sector-diversification cap)."""
        snapshot = self._fresh_snapshot(symbol.upper())
        return snapshot.sector if snapshot else None

    def get_long_term_outlook(self, symbol: str) -> LongTermOutlook:
        symbol = symbol.upper()
        snapshot = self._fresh_snapshot(symbol)
        trend_up = self._long_term_trend_up(symbol)
        return evaluate_long_term_outlook(snapshot, trend_up)

    def _long_term_trend_up(self, symbol: str) -> bool | None:
        indicators = self._scanner_engine.compute_indicators(symbol)
        if indicators is None or indicators.ema50 is None or indicators.ema200 is None:
            return None
        return indicators.ema50 > indicators.ema200
