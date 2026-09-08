"""Periodically fills in the N-days-later price for tracked signal changes
(app.signals.tracking_repository) once enough time has passed. Recording a
*new* signal change happens elsewhere, in ScannerService._run_scan_cycle,
since that's where the "did the signal just change" comparison already
lives -- this service only handles the "look back and fill due checkpoints"
half, which needs its own timer independent of the scan cycle."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy.orm import Session, sessionmaker

from app.core.logging import get_logger
from app.services.scanner_service import ScannerService
from app.signals import tracking_repository
from app.signals.tracking_db_models import CHECKPOINT_DAYS

logger = get_logger(__name__)


class SignalTrackingService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        market: str,
        scanner_service: ScannerService,
        tick_interval_seconds: float = 3600.0,
    ) -> None:
        self._session_factory = session_factory
        self._market = market
        self._scanner_service = scanner_service
        self._tick_interval = tick_interval_seconds
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        self._stopping = False
        self._task = asyncio.create_task(self._loop(), name=f"signal-tracking-{self._market}")

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
                await asyncio.to_thread(self._tick_sync)
            except Exception:  # noqa: BLE001 - a bad tick must not kill the loop
                logger.exception("signal tracking tick failed for market %s", self._market)
            await asyncio.sleep(self._tick_interval)

    def _tick_sync(self) -> None:
        now = datetime.now(timezone.utc)
        filled = 0
        for horizon_days in CHECKPOINT_DAYS:
            due_ids = tracking_repository.find_due_ids(
                self._session_factory, self._market, horizon_days, now
            )
            for row_id in due_ids:
                symbol = tracking_repository.get_symbol(self._session_factory, row_id)
                if symbol is None:
                    continue
                current = self._scanner_service.get_signal(symbol)
                if current is None:
                    continue  # not tracked/scored right now -- try again next tick
                tracking_repository.fill_checkpoint(
                    self._session_factory, row_id, horizon_days, current.price
                )
                filled += 1
        if filled:
            logger.info("signal tracking: filled %d checkpoint(s) for market %s", filled, self._market)
