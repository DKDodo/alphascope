"""Runs a self-driving N-day paper trading simulation against the scanner's
own signals: no human decides trades here, the rule-based SignalEngine does.

Design choices, made explicit because they directly shape the results:
- Entry: opens a position on STRONG_BUY_SETUP or BUY_SETUP if a slot is free.
- Exit: closes on stop-loss/take-profit being hit, or the signal dropping to
  AVOID, or the run's time window ending (mark-to-market close).
- Sizing: risk-based (RISK_PER_TRADE_FRACTION of cash per trade, sized
  inversely to the stop distance) capped by MAX_POSITION_ALLOCATION_FRACTION
  -- a volatile/wide-ATR symbol gets fewer shares than a calm one for the
  same dollar risk, rather than every symbol getting the same cash share
  regardless of how far it could move against you. Concurrent-position cap
  forces diversification (though not across sectors -- see README).
- Stop-loss trails up (ATR distance from current price) as a position gains,
  never back down: locks in gains instead of giving back a whole reversal.
- Persisted to SQLite (see db_models.py) so the run survives a process
  restart — critical for a "7-day" claim to mean anything on a host that
  can sleep/redeploy.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.autotrader.db_models import SimulationPosition, SimulationRun, SimulationTradeLog
from app.autotrader.models import (
    SimulationPositionOut,
    SimulationStatusOut,
    SimulationStatusValue,
    SimulationTradeOut,
)
from app.core.exceptions import RiskCalculationError
from app.core.logging import get_logger
from app.risk.risk_engine import DEFAULT_STOP_ATR_MULTIPLIER
from app.services.scanner_service import ScannerService
from app.signals.models import SignalResult, SignalType

logger = get_logger(__name__)

RISK_PER_TRADE_FRACTION = 0.02  # max fraction of cash risked (to the stop) on a single new position
MAX_POSITION_ALLOCATION_FRACTION = 0.20  # hard cap on any position's cash share, even if risk-sizing wants more
TRAILING_STOP_ATR_MULTIPLIER = DEFAULT_STOP_ATR_MULTIPLIER  # same distance the initial stop uses
MAX_CONCURRENT_POSITIONS = 5
MIN_TRADE_VALUE = 1.0  # skip a buy that would be smaller than this (dust)


def _as_utc(dt: datetime) -> datetime:
    """SQLite's DateTime column drops tzinfo on round-trip, so every
    datetime read back from the DB comes back naive — normalize to
    timezone-aware UTC before comparing against datetime.now(timezone.utc)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class AutoTraderService:
    def __init__(
        self,
        session_factory,
        market: str,
        currency_symbol: str,
        scanner_service: ScannerService,
        tick_interval_seconds: float = 30.0,
    ) -> None:
        self._session_factory = session_factory
        self._market = market
        self._currency_symbol = currency_symbol
        self._scanner_service = scanner_service
        self._tick_interval = tick_interval_seconds
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        self._stopping = False
        self._task = asyncio.create_task(self._loop(), name=f"autotrader-{self._market}")

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
            except Exception:  # noqa: BLE001 - a bad tick must not kill the simulation loop
                logger.exception("autotrader tick failed for market %s", self._market)
            await asyncio.sleep(self._tick_interval)

    # -- public, session-managing API -------------------------------------------------

    def start_run(self, initial_cash: float, duration_days: float) -> SimulationStatusOut:
        with self._session() as db:
            active = self._get_active_run(db)
            if active is not None:
                raise RiskCalculationError(
                    "Zaten çalışan bir simülasyon var. Yenisini başlatmadan önce mevcut "
                    "simülasyonun bitmesini bekleyin."
                )
            now = datetime.now(timezone.utc)
            run = SimulationRun(
                market=self._market,
                status="RUNNING",
                started_at=now,
                ends_at=now + timedelta(days=duration_days),
                initial_cash=initial_cash,
                cash=initial_cash,
                realized_pnl=0.0,
                currency_symbol=self._currency_symbol,
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            logger.info(
                "simulation started (market=%s, cash=%.2f, duration=%.1fd)",
                self._market, initial_cash, duration_days,
            )
            return self._to_status_out(db, run)

    def stop_run(self) -> SimulationStatusOut:
        """Manually ends the active run right now: liquidates every open
        position at the current market price (same mark-to-market close the
        scheduled end-of-run uses) and marks it COMPLETED. Irreversible --
        there's no "resume", the user has to start a fresh run."""
        with self._session() as db:
            run = self._get_active_run(db)
            if run is None:
                raise RiskCalculationError("Durdurulacak çalışan bir simülasyon yok.")
            self._close_run(db, run, reason="Kullanıcı tarafından durduruldu")
            return self._to_status_out(db, run)

    def get_status(self) -> SimulationStatusOut:
        with self._session() as db:
            run = self._get_latest_run(db)
            if run is None:
                return SimulationStatusOut(
                    status=SimulationStatusValue.NOT_STARTED,
                    market=self._market,
                    currency_symbol=self._currency_symbol,
                )
            return self._to_status_out(db, run)

    # -- tick: the actual trading logic, called periodically ---------------------------

    def _tick_sync(self) -> None:
        with self._session() as db:
            run = self._get_active_run(db)
            if run is None:
                return

            now = datetime.now(timezone.utc)
            if now >= _as_utc(run.ends_at):
                self._close_run(db, run)
                return

            self._process_exits(db, run)
            self._process_entries(db, run)
            db.commit()

    def _process_exits(self, db: Session, run: SimulationRun) -> None:
        positions = db.execute(
            select(SimulationPosition).where(SimulationPosition.run_id == run.id)
        ).scalars().all()

        for position in positions:
            signal = self._scanner_service.get_signal(position.symbol)
            if signal is None:
                continue
            self._update_trailing_stop(position, signal)
            reason = self._exit_reason(position, signal.price, signal.signal)
            if reason is not None:
                self._sell(db, run, position, signal.price, reason)

    def _update_trailing_stop(self, position: SimulationPosition, signal: SignalResult) -> None:
        """Ratchets the stop up as price rises, never back down. Uses current
        ATR (not the ATR at entry) so the trailing distance adapts if the
        symbol's volatility changes while the position is open."""
        if position.stop_loss is None or signal.risk_analysis is None:
            return
        atr = signal.risk_analysis.atr
        if atr <= 0:
            return
        trailing_candidate = signal.price - atr * TRAILING_STOP_ATR_MULTIPLIER
        if trailing_candidate > position.stop_loss:
            position.stop_loss = trailing_candidate

    def _exit_reason(self, position: SimulationPosition, price: float, signal: SignalType) -> str | None:
        if position.stop_loss is not None and price <= position.stop_loss:
            return "Zarar-kes seviyesine ulaşıldı"
        if position.take_profit is not None and price >= position.take_profit:
            return "Kâr-al seviyesine ulaşıldı"
        if signal == SignalType.AVOID:
            return "Sinyal KAÇININ'a döndü"
        return None

    def _process_entries(self, db: Session, run: SimulationRun) -> None:
        open_count = db.execute(
            select(SimulationPosition).where(SimulationPosition.run_id == run.id)
        ).scalars().all()
        open_symbols = {p.symbol for p in open_count}
        if len(open_symbols) >= MAX_CONCURRENT_POSITIONS:
            return

        candidates = [
            r for r in self._scanner_service.get_scan_results()
            if r.signal in (SignalType.STRONG_BUY_SETUP, SignalType.BUY_SETUP)
            and r.symbol not in open_symbols
        ]
        candidates.sort(key=lambda r: r.score, reverse=True)

        for result in candidates:
            if len(open_symbols) >= MAX_CONCURRENT_POSITIONS:
                break
            detail = self._scanner_service.get_signal(result.symbol)
            stop_loss = detail.risk_analysis.stop_loss if detail and detail.risk_analysis else None
            take_profit = detail.risk_analysis.take_profit_1 if detail and detail.risk_analysis else None

            allocation = self._position_size(run, result.price, stop_loss)
            if allocation < MIN_TRADE_VALUE or allocation > run.cash:
                continue

            quantity = allocation / result.price
            run.cash -= allocation
            position = SimulationPosition(
                run_id=run.id,
                symbol=result.symbol,
                quantity=quantity,
                average_price=result.price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                opened_at=datetime.now(timezone.utc),
            )
            db.add(position)
            db.add(SimulationTradeLog(
                run_id=run.id,
                symbol=result.symbol,
                action="BUY",
                price=result.price,
                quantity=quantity,
                reason=f"Sinyal {result.signal.value} (skor {result.score})",
                realized_pnl=None,
                timestamp=datetime.now(timezone.utc),
            ))
            open_symbols.add(result.symbol)
            logger.info(
                "[%s] simulation BUY %s x%.4f @ %.4f", self._market, result.symbol, quantity, result.price
            )

    def _position_size(self, run: SimulationRun, entry_price: float, stop_loss: float | None) -> float:
        """Cash value to allocate to a new position. Risk-based: sized so
        that hitting the stop loses about the same dollar amount
        (RISK_PER_TRADE_FRACTION of cash) regardless of the symbol -- a
        volatile symbol with a stop far from entry gets fewer shares (a
        smaller position) than a calm one, for the same risk. Falls back to
        the flat MAX_POSITION_ALLOCATION_FRACTION cap when there's no usable
        stop distance to size against (e.g. ATR unavailable yet)."""
        max_position_value = run.cash * MAX_POSITION_ALLOCATION_FRACTION
        if stop_loss is None or stop_loss >= entry_price:
            return max_position_value
        risk_per_share = entry_price - stop_loss
        risk_budget = run.cash * RISK_PER_TRADE_FRACTION
        position_value_from_risk = (risk_budget / risk_per_share) * entry_price
        return min(position_value_from_risk, max_position_value)

    def _sell(self, db: Session, run: SimulationRun, position: SimulationPosition, price: float, reason: str) -> None:
        proceeds = position.quantity * price
        pnl = (price - position.average_price) * position.quantity
        run.cash += proceeds
        run.realized_pnl += pnl
        db.add(SimulationTradeLog(
            run_id=run.id,
            symbol=position.symbol,
            action="SELL",
            price=price,
            quantity=position.quantity,
            reason=reason,
            realized_pnl=pnl,
            timestamp=datetime.now(timezone.utc),
        ))
        db.delete(position)
        logger.info(
            "[%s] simulation SELL %s x%.4f @ %.4f (pnl=%.2f, reason=%s)",
            self._market, position.symbol, position.quantity, price, pnl, reason,
        )

    def _close_run(
        self,
        db: Session,
        run: SimulationRun,
        reason: str = "Simülasyon süresi doldu (mark-to-market kapanış)",
    ) -> None:
        positions = db.execute(
            select(SimulationPosition).where(SimulationPosition.run_id == run.id)
        ).scalars().all()
        for position in positions:
            signal = self._scanner_service.get_signal(position.symbol)
            price = signal.price if signal is not None else position.average_price
            self._sell(db, run, position, price, reason)
        run.status = "COMPLETED"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("[%s] simulation completed (%s), realized_pnl=%.2f", self._market, reason, run.realized_pnl)

    # -- helpers ------------------------------------------------------------------------

    def _get_active_run(self, db: Session) -> SimulationRun | None:
        return db.execute(
            select(SimulationRun)
            .where(SimulationRun.market == self._market, SimulationRun.status == "RUNNING")
            .order_by(SimulationRun.id.desc())
        ).scalars().first()

    def _get_latest_run(self, db: Session) -> SimulationRun | None:
        return db.execute(
            select(SimulationRun)
            .where(SimulationRun.market == self._market)
            .order_by(SimulationRun.id.desc())
        ).scalars().first()

    def _to_status_out(self, db: Session, run: SimulationRun) -> SimulationStatusOut:
        positions = db.execute(
            select(SimulationPosition).where(SimulationPosition.run_id == run.id)
        ).scalars().all()
        trades = db.execute(
            select(SimulationTradeLog)
            .where(SimulationTradeLog.run_id == run.id)
            .order_by(SimulationTradeLog.id.desc())
            .limit(50)
        ).scalars().all()

        position_outs: list[SimulationPositionOut] = []
        unrealized_total = 0.0
        for p in positions:
            signal = self._scanner_service.get_signal(p.symbol)
            current_price = signal.price if signal is not None else None
            unrealized = (current_price - p.average_price) * p.quantity if current_price is not None else None
            if unrealized is not None:
                unrealized_total += unrealized
            position_outs.append(SimulationPositionOut(
                symbol=p.symbol, quantity=round(p.quantity, 6), average_price=round(p.average_price, 4),
                current_price=round(current_price, 4) if current_price is not None else None,
                unrealized_pnl=round(unrealized, 2) if unrealized is not None else None,
                stop_loss=p.stop_loss, take_profit=p.take_profit,
            ))

        positions_value = sum(
            (po.current_price or po.average_price) * po.quantity for po in position_outs
        )
        equity = run.cash + positions_value
        total_return_pct = (equity - run.initial_cash) / run.initial_cash * 100.0 if run.initial_cash else None

        now = datetime.now(timezone.utc)
        days_remaining = (
            max(0.0, (_as_utc(run.ends_at) - now).total_seconds() / 86400.0)
            if run.status == "RUNNING" else 0.0
        )

        trade_count = db.execute(select(SimulationTradeLog).where(SimulationTradeLog.run_id == run.id)).scalars().all()

        return SimulationStatusOut(
            status=SimulationStatusValue.RUNNING if run.status == "RUNNING" else SimulationStatusValue.COMPLETED,
            market=self._market,
            currency_symbol=self._currency_symbol,
            started_at=run.started_at,
            ends_at=run.ends_at,
            completed_at=run.completed_at,
            days_remaining=round(days_remaining, 3),
            initial_cash=run.initial_cash,
            cash=round(run.cash, 2),
            equity=round(equity, 2),
            realized_pnl=round(run.realized_pnl, 2),
            unrealized_pnl=round(unrealized_total, 2),
            total_return_pct=round(total_return_pct, 2) if total_return_pct is not None else None,
            trade_count=len(trade_count),
            positions=position_outs,
            recent_trades=[
                SimulationTradeOut(
                    symbol=t.symbol, action=t.action, price=t.price, quantity=round(t.quantity, 6),
                    reason=t.reason, realized_pnl=t.realized_pnl, timestamp=t.timestamp,
                )
                for t in trades
            ],
        )

    def _session(self):
        return _SessionContext(self._session_factory)


class _SessionContext:
    """Tiny sync context manager so callers get `with self._session() as db:`
    without pulling in a full unit-of-work abstraction for three call sites."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory
        self._db: Session | None = None

    def __enter__(self) -> Session:
        self._db = self._session_factory()
        return self._db

    def __exit__(self, exc_type, exc, tb) -> None:
        assert self._db is not None
        self._db.close()
