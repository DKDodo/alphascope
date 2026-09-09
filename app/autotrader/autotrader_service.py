"""Runs a self-driving N-day paper trading simulation against the scanner's
own signals: no human decides trades here, the rule-based SignalEngine does.

Design choices, made explicit because they directly shape the results:
- Entry: opens a position once a symbol's raw score clears
  AUTOTRADER_ENTRY_SCORE_MIN, if a slot is free -- this is AutoTrader's own,
  deliberately looser bar, decoupled from the dashboard's STRONG_BUY_SETUP/
  BUY_SETUP labels (signal_engine.py's _THRESHOLDS). A backtest found the
  display's 75/85 bar so strict AutoTrader sat in ~96% cash (~0.16
  qualifying candidates/day across the whole universe) -- see app/backtest/.
- Exit: closes on stop-loss/take-profit being hit, or the signal reading
  AVOID for AVOID_EXIT_STREAK_REQUIRED consecutive checks in a row (not a
  single reading -- that whipsawed positions out on routine noise, the
  same backtest found), or the run's time window ending (mark-to-market close).
- Sizing: risk-based (RISK_PER_TRADE_FRACTION of cash per trade, sized
  inversely to the stop distance) capped by MAX_POSITION_ALLOCATION_FRACTION
  -- a volatile/wide-ATR symbol gets fewer shares than a calm one for the
  same dollar risk, rather than every symbol getting the same cash share
  regardless of how far it could move against you. Concurrent-position cap
  forces diversification, further reinforced by the sector cap below.
- Stop-loss trails up (ATR distance from current price) as a position gains,
  never back down: locks in gains instead of giving back a whole reversal.
- Stop/target sizing defaults to ATR (volatility-adaptive, see RiskEngine),
  but a run can opt into fixed percentages instead (start_run()'s
  stop_loss_pct/take_profit_pct, chosen once at start time) -- e.g. "5%
  stop, 10% target" regardless of the symbol's own volatility. TP2 and the
  trailing stop derive from the same fixed percentage in that mode (see
  FIXED_PCT_TP2_RATIO), so the two-step partial exit and trailing-stop
  mechanics below work identically either way. Backtesting only ever
  replays the ATR-based default -- a run's chosen fixed percentages aren't
  historical parameters to validate, just a live trading preference.
- Persisted to SQLite (see db_models.py) so the run survives a process
  restart — critical for a "7-day" claim to mean anything on a host that
  can sleep/redeploy.
- Sector-capped: at most MAX_POSITIONS_PER_SECTOR open positions share the
  same FundamentalsService sector, so the concurrent-position cap forces
  real diversification instead of five correlated bets in one industry.
  Skipped entirely when fundamentals data isn't available (e.g. crypto).
- A second, independent entry path opens on a STRONG DipOpportunity even
  when the trend-following signal isn't a buy setup -- see app/signals/dip_detector.py
  for why the two can disagree. Trade-logged with a distinguishable reason
  so it's never confused with a trend-based buy.
- Both entry paths additionally require the daily-bar trend (EMA50 vs
  EMA200, see app/daily_trend/) not to be confirmed down, and position
  sizing is derated when VIX is elevated (see MacroService) -- the
  Opportunity Score itself never uses either signal, only this trading
  decision does.
- Both entry paths also skip a symbol whose long-term fundamentals outlook
  (see app/fundamentals/long_term_scoring.py) is confirmed UNFAVORABLE --
  a strong short-term setup on a fundamentally deteriorating company is
  exactly the kind of divergence worth being cautious about.
- Both entry paths likewise skip a symbol whose recent news sentiment reads
  a confirmed NEGATIVE, after filtering the cached headlines down to ones
  that actually name the company (see app/news/relevance.py and
  app/news/symbol_aliases.py -- Yahoo attributes a lot of headlines to a
  symbol that are really general market noise or another company's story)
  with at least MIN_RELEVANT_HEADLINES_FOR_NEWS_GATE relevant headlines
  behind the reading. Same fail-open spirit as every other optional gate here.
- Portfolio-level circuit breaker: once a run's equity has drawn down
  MAX_DRAWDOWN_FRACTION from its peak, new entries pause (existing
  positions keep exiting normally) until it recovers.
- Take-profit is taken in two steps: PARTIAL_EXIT_FRACTION of the position
  closes at TP1, the remainder's target is promoted to TP2 and its stop
  keeps trailing -- locks in some gain early without fully exiting a move
  that keeps running.
- A flat TRANSACTION_COST_RATE is charged on both legs of every trade
  (baked into the cost basis on entry, netted out of proceeds on exit) so
  reported returns aren't an unrealistic zero-friction fantasy.
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
from app.fundamentals.fundamentals_service import FundamentalsService
from app.fundamentals.models import LongTermOutlookLabel
from app.macro.macro_service import MacroService
from app.news.models import SentimentLabel
from app.news.news_service import NewsService
from app.news.relevance import evaluate_relevant_sentiment
from app.risk.risk_engine import (
    DEFAULT_STOP_ATR_MULTIPLIER,
    DEFAULT_TP1_ATR_MULTIPLIER,
    DEFAULT_TP2_ATR_MULTIPLIER,
)
from app.services.scanner_service import ScannerService
from app.signals.models import DipConfidence, SignalResult, SignalType

logger = get_logger(__name__)

RISK_PER_TRADE_FRACTION = 0.02  # max fraction of cash risked (to the stop) on a single new position
MAX_POSITION_ALLOCATION_FRACTION = 0.20  # hard cap on any position's cash share, even if risk-sizing wants more
TRAILING_STOP_ATR_MULTIPLIER = DEFAULT_STOP_ATR_MULTIPLIER  # same distance the initial stop uses
MAX_CONCURRENT_POSITIONS = 5
MIN_TRADE_VALUE = 1.0  # skip a buy that would be smaller than this (dust)
MAX_POSITIONS_PER_SECTOR = 2  # forces diversification even within the concurrent-position cap
DIP_ENTRY_MIN_CONFIDENCE = DipConfidence.STRONG  # only the highest-confidence dips get a secondary entry
VIX_ELEVATED_THRESHOLD = 20.0  # -> halve new-position risk
VIX_HIGH_THRESHOLD = 30.0  # -> quarter new-position risk
# RISK_PER_TRADE_FRACTION * MAX_CONCURRENT_POSITIONS puts a ~10% theoretical
# ceiling on simultaneous stop-outs -- this catches a genuinely bad streak
# without tripping on ordinary day-to-day volatility.
MAX_DRAWDOWN_FRACTION = 0.10
PARTIAL_EXIT_FRACTION = 0.5  # fraction of the position closed at TP1
TRANSACTION_COST_RATE = 0.001  # 0.1% per leg (~0.2% round trip) -- one flat, simple assumption across all 3 markets
# Calibrated via app/backtest/ against real Global (3y) + BIST (2y) history,
# not guessed -- a grid sweep of entry ∈ {45,50,55,60,65} x streak ∈
# {1,2,3,5} found streak=3 dominant almost everywhere, and entry=60 the
# best cross-market average (Global +43.8%, BIST +13.9%, both solidly
# positive -- lower entry values fit Global better but went negative on
# BIST, a sign of overfitting to one market's history). AutoTrader's own
# entry bar, independent of signal_engine.py's STRONG_BUY_SETUP/BUY_SETUP
# display thresholds (75/85).
AUTOTRADER_ENTRY_SCORE_MIN = 60
# Same sweep: streak=3 was the dominant choice almost regardless of the
# entry threshold (1-2 whipsawed too readily, 5 held losers too long,
# especially on BIST). "Ardışık kontrol" means consecutive evaluations of
# this position -- a live AutoTrader tick (AUTOTRADER_TICK_INTERVAL_SECONDS,
# default 60s) in production, a trading day in the backtest (which only
# re-evaluates once per day, see app/backtest/backtest_engine.py). Same
# constant, different real-world time span in each context -- an
# intentional simplification, not a precision claim; the goal in both is
# just "don't exit on one noisy reading."
AVOID_EXIT_STREAK_REQUIRED = 3
# When a run uses fixed-percentage stop/target (see start_run()) instead of
# ATR sizing, TP2 is still derived as a further extension of TP1 rather than
# a second user input -- this preserves the same TP2/TP1 ratio the ATR-based
# defaults imply, so the existing two-step partial-exit mechanism keeps
# working identically in both modes.
FIXED_PCT_TP2_RATIO = DEFAULT_TP2_ATR_MULTIPLIER / DEFAULT_TP1_ATR_MULTIPLIER
# Same "don't act on a thin sample" rule already used elsewhere in this
# codebase for the identical class of question -- AVOID_EXIT_STREAK_REQUIRED
# above and app/signals/tracking_repository.py's _MIN_SAMPLES_FOR_SUMMARY are
# both already 3, so this isn't a fresh guess, it's this project's existing
# standard for "how many independent observations before a statistic is
# trustworthy enough to act on."
MIN_RELEVANT_HEADLINES_FOR_NEWS_GATE = 3


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
        fundamentals_service: FundamentalsService | None = None,
        macro_service: MacroService | None = None,
        news_service: NewsService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._market = market
        self._currency_symbol = currency_symbol
        self._scanner_service = scanner_service
        self._tick_interval = tick_interval_seconds
        self._fundamentals_service = fundamentals_service
        self._macro_service = macro_service
        self._news_service = news_service
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

    def start_run(
        self,
        initial_cash: float,
        duration_days: float,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
    ) -> SimulationStatusOut:
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
                peak_equity=initial_cash,
                currency_symbol=self._currency_symbol,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
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
            self._update_trailing_stop(run, position, signal)
            self._update_avoid_streak(position, signal.signal)

            if self._should_take_partial_profit(position, signal.price):
                self._partial_sell(db, run, position, signal.price)
                continue  # remaining half re-evaluated against the promoted TP2 next tick

            reason = self._exit_reason(position, signal.price, signal.signal)
            if reason is not None:
                self._sell(db, run, position, signal.price, reason)

    def _update_trailing_stop(
        self, run: SimulationRun, position: SimulationPosition, signal: SignalResult
    ) -> None:
        """Ratchets the stop up as price rises, never back down. In a fixed-
        percentage run (run.stop_loss_pct set -- see start_run()), the
        trailing distance is that same percentage of current price instead
        of ATR, so the two modes stay conceptually parallel. ATR mode uses
        current ATR (not the ATR at entry) so the trailing distance adapts if
        the symbol's volatility changes while the position is open."""
        if position.stop_loss is None:
            return
        if run.stop_loss_pct is not None:
            trailing_candidate = signal.price * (1 - run.stop_loss_pct / 100)
        else:
            if signal.risk_analysis is None:
                return
            atr = signal.risk_analysis.atr
            if atr <= 0:
                return
            trailing_candidate = signal.price - atr * TRAILING_STOP_ATR_MULTIPLIER
        if trailing_candidate > position.stop_loss:
            position.stop_loss = trailing_candidate

    def _update_avoid_streak(self, position: SimulationPosition, signal: SignalType) -> None:
        """Counts consecutive exit-check passes the signal has read AVOID,
        resetting the moment it doesn't -- a single noisy AVOID reading
        (a routine pullback, not a real reversal) must not by itself close
        the position; see AVOID_EXIT_STREAK_REQUIRED."""
        if signal == SignalType.AVOID:
            position.avoid_streak = (position.avoid_streak or 0) + 1
        else:
            position.avoid_streak = 0

    def _exit_reason(self, position: SimulationPosition, price: float, signal: SignalType) -> str | None:
        if position.stop_loss is not None and price <= position.stop_loss:
            return "Zarar-kes seviyesine ulaşıldı"
        if position.take_profit is not None and price >= position.take_profit:
            return "Kâr-al seviyesine ulaşıldı"
        if (position.avoid_streak or 0) >= AVOID_EXIT_STREAK_REQUIRED:
            return f"Sinyal {AVOID_EXIT_STREAK_REQUIRED} ardışık kontrolde KAÇININ'da kaldı"
        return None

    def _should_take_partial_profit(self, position: SimulationPosition, price: float) -> bool:
        return (
            not position.partial_exit_done
            and position.take_profit_2 is not None
            and position.take_profit is not None
            and price >= position.take_profit
        )

    def _partial_sell(self, db: Session, run: SimulationRun, position: SimulationPosition, price: float) -> None:
        """Closes PARTIAL_EXIT_FRACTION of the position at TP1 and promotes
        the remainder's target to TP2 -- locks in some of the gain while
        staying in for a bigger move, instead of the all-or-nothing exit
        _sell() does. The remaining half keeps its trailing stop untouched."""
        sold_quantity = position.quantity * PARTIAL_EXIT_FRACTION
        net_price = price * (1 - TRANSACTION_COST_RATE)
        proceeds = sold_quantity * net_price
        pnl = (net_price - position.average_price) * sold_quantity
        run.cash += proceeds
        run.realized_pnl += pnl
        db.add(SimulationTradeLog(
            run_id=run.id,
            symbol=position.symbol,
            action="SELL",
            price=price,
            quantity=sold_quantity,
            reason=f"Kısmi Kâr Alım (TP1) — kalan %{round((1 - PARTIAL_EXIT_FRACTION) * 100)} TP2'ye taşındı",
            realized_pnl=pnl,
            timestamp=datetime.now(timezone.utc),
        ))
        position.quantity -= sold_quantity
        position.partial_exit_done = True
        position.take_profit = position.take_profit_2
        logger.info(
            "[%s] simulation PARTIAL SELL %s x%.4f @ %.4f (pnl=%.2f, remainder target -> %.4f)",
            self._market, position.symbol, sold_quantity, price, pnl, position.take_profit,
        )

    def _process_entries(self, db: Session, run: SimulationRun) -> None:
        open_positions = db.execute(
            select(SimulationPosition).where(SimulationPosition.run_id == run.id)
        ).scalars().all()
        open_symbols = {p.symbol for p in open_positions}

        equity = self._compute_equity(run, open_positions)
        run.peak_equity = max(run.peak_equity or 0.0, equity)
        drawdown = (run.peak_equity - equity) / run.peak_equity if run.peak_equity > 0 else 0.0
        if drawdown >= MAX_DRAWDOWN_FRACTION:
            logger.info(
                "[%s] autotrader paused: drawdown %.1f%% >= %.1f%% circuit breaker (equity=%.2f, peak=%.2f)",
                self._market, drawdown * 100, MAX_DRAWDOWN_FRACTION * 100, equity, run.peak_equity,
            )
            return  # existing positions still exit normally via _process_exits(); only new entries pause

        if len(open_symbols) >= MAX_CONCURRENT_POSITIONS:
            return

        # Sector distribution of currently-open positions -- empty (so no
        # cap is ever applied) when fundamentals data isn't available for
        # this market (crypto) or hasn't arrived yet.
        open_sectors: dict[str, int] = {}
        if self._fundamentals_service is not None:
            for p in open_positions:
                sector = self._fundamentals_service.get_sector(p.symbol)
                if sector:
                    open_sectors[sector] = open_sectors.get(sector, 0) + 1

        risk_multiplier = self._risk_multiplier_from_vix()
        logger.info("[%s] autotrader risk_multiplier=%.2f (vix-derated)", self._market, risk_multiplier)

        all_results = self._scanner_service.get_scan_results()
        trend_candidates = [
            r for r in all_results
            if r.score >= AUTOTRADER_ENTRY_SCORE_MIN
            and r.symbol not in open_symbols
            and r.daily_trend_up is not False
            and self._passes_long_term_outlook(r.symbol)
            and self._passes_news_sentiment(r.symbol)
        ]
        trend_candidates.sort(key=lambda r: r.score, reverse=True)
        trend_symbols = {r.symbol for r in trend_candidates}

        # Secondary entry path: a STRONG mean-reversion dip can fire even
        # when the trend-following signal isn't a buy setup (that's the
        # whole point of DipOpportunity being separate -- see dip_detector.py).
        # Still requires the daily trend not to be confirmed down, since
        # "buying the dip" into a structural downtrend is the riskiest
        # version of this trade.
        dip_candidates = [
            r for r in all_results
            if r.dip_opportunity is not None
            and r.dip_opportunity.confidence == DIP_ENTRY_MIN_CONFIDENCE
            and r.symbol not in open_symbols
            and r.symbol not in trend_symbols
            and r.daily_trend_up is not False
            and self._passes_long_term_outlook(r.symbol)
            and self._passes_news_sentiment(r.symbol)
        ]

        # Trend-based candidates get first claim on the limited slots; dip
        # candidates only fill what's left over.
        candidates = trend_candidates + dip_candidates

        for result in candidates:
            if len(open_symbols) >= MAX_CONCURRENT_POSITIONS:
                break

            sector = self._fundamentals_service.get_sector(result.symbol) if self._fundamentals_service else None
            if sector and open_sectors.get(sector, 0) >= MAX_POSITIONS_PER_SECTOR:
                continue

            detail = self._scanner_service.get_signal(result.symbol)
            if run.stop_loss_pct is not None and run.take_profit_pct is not None:
                # User-chosen fixed percentages (see start_run()) override
                # RiskEngine's ATR-based sizing entirely for this run.
                stop_loss = result.price * (1 - run.stop_loss_pct / 100)
                take_profit = result.price * (1 + run.take_profit_pct / 100)
                take_profit_2 = result.price * (1 + run.take_profit_pct * FIXED_PCT_TP2_RATIO / 100)
            else:
                stop_loss = detail.risk_analysis.stop_loss if detail and detail.risk_analysis else None
                take_profit = detail.risk_analysis.take_profit_1 if detail and detail.risk_analysis else None
                take_profit_2 = detail.risk_analysis.take_profit_2 if detail and detail.risk_analysis else None

            allocation = self._position_size(run, result.price, stop_loss, risk_multiplier)
            effective_cost = allocation * (1 + TRANSACTION_COST_RATE)
            if allocation < MIN_TRADE_VALUE or effective_cost > run.cash:
                continue

            is_dip_entry = result.symbol not in trend_symbols
            reason = (
                f"Dip Fırsatı ({result.dip_opportunity.confidence.value} güven) — aşırı satım tepki alımı"
                if is_dip_entry
                # Raw score, not the SignalType label -- a qualifying candidate
                # can sit below the dashboard's BUY_SETUP bar (75) since
                # AUTOTRADER_ENTRY_SCORE_MIN is deliberately looser.
                else f"AutoTrader giriş eşiği aşıldı (skor {result.score}, görüntülenen sinyal: {result.signal.value})"
            )

            quantity = allocation / result.price
            run.cash -= effective_cost
            position = SimulationPosition(
                run_id=run.id,
                symbol=result.symbol,
                quantity=quantity,
                # Cost basis includes the buy-side fee, same as a real
                # brokerage statement -- see _sell()/_partial_sell() for the
                # matching sell-side fee that nets out a true round-trip P&L.
                average_price=result.price * (1 + TRANSACTION_COST_RATE),
                stop_loss=stop_loss,
                take_profit=take_profit,
                take_profit_2=take_profit_2,
                opened_at=datetime.now(timezone.utc),
            )
            db.add(position)
            db.add(SimulationTradeLog(
                run_id=run.id,
                symbol=result.symbol,
                action="BUY",
                price=result.price,
                quantity=quantity,
                reason=reason,
                realized_pnl=None,
                timestamp=datetime.now(timezone.utc),
            ))
            open_symbols.add(result.symbol)
            if sector:
                open_sectors[sector] = open_sectors.get(sector, 0) + 1
            logger.info(
                "[%s] simulation BUY %s x%.4f @ %.4f (%s)",
                self._market, result.symbol, quantity, result.price, reason,
            )

    def _risk_multiplier_from_vix(self) -> float:
        """Derates new-position risk when the VIX is elevated -- purely a
        trading-decision input, never fed into the Opportunity Score itself
        (see app/macro/models.py). Fails open (1.0, no derating) whenever
        macro data isn't wired up or VIX isn't in this market's indicator
        list -- BIST's macro_indicators has no ^VIX today."""
        if self._macro_service is None:
            return 1.0
        vix = next(
            (i.price for i in self._macro_service.get_indicators() if i.symbol == "^VIX" and i.price is not None),
            None,
        )
        if vix is None:
            return 1.0
        if vix >= VIX_HIGH_THRESHOLD:
            return 0.25
        if vix >= VIX_ELEVATED_THRESHOLD:
            return 0.5
        return 1.0

    def _passes_long_term_outlook(self, symbol: str) -> bool:
        """Skips a symbol only on a confirmed-UNFAVORABLE long-term outlook
        (P/E, margins, growth, leverage, analyst consensus -- see
        long_term_scoring.py) -- NEUTRAL/INSUFFICIENT_DATA pass through, same
        fail-open philosophy as the daily-trend gate. get_long_term_outlook()
        only reads FundamentalsService's cache and the scanner's already-
        computed indicators, no network call, so this is cheap enough to
        call per candidate."""
        if self._fundamentals_service is None:
            return True
        outlook = self._fundamentals_service.get_long_term_outlook(symbol)
        return outlook.label != LongTermOutlookLabel.UNFAVORABLE

    def _passes_news_sentiment(self, symbol: str) -> bool:
        """Skips a symbol only when its recent news sentiment reads a
        confirmed NEGATIVE after filtering cached headlines down to ones
        that actually name the company (see app/news/relevance.py) -- Yahoo
        attributes a lot of headlines to a symbol that are really general
        market noise or another company's story (empirically verified).
        Also fails open below MIN_RELEVANT_HEADLINES_FOR_NEWS_GATE relevant
        headlines -- a single relevant headline is too thin a sample to act
        on. Same fail-open spirit as every other optional gate here."""
        if self._news_service is None:
            return True
        verdict = evaluate_relevant_sentiment(self._news_service.get_news(symbol), symbol)
        if verdict.relevant_count < MIN_RELEVANT_HEADLINES_FOR_NEWS_GATE:
            return True
        return verdict.overall != SentimentLabel.NEGATIVE

    def _compute_equity(self, run: SimulationRun, positions: list[SimulationPosition]) -> float:
        positions_value = 0.0
        for p in positions:
            signal = self._scanner_service.get_signal(p.symbol)
            price = signal.price if signal is not None else p.average_price
            positions_value += price * p.quantity
        return run.cash + positions_value

    def _position_size(
        self, run: SimulationRun, entry_price: float, stop_loss: float | None, risk_multiplier: float = 1.0
    ) -> float:
        """Cash value to allocate to a new position. Risk-based: sized so
        that hitting the stop loses about the same dollar amount
        (RISK_PER_TRADE_FRACTION of cash, scaled by risk_multiplier) regardless
        of the symbol -- a volatile symbol with a stop far from entry gets
        fewer shares (a smaller position) than a calm one, for the same risk.
        Falls back to the flat MAX_POSITION_ALLOCATION_FRACTION cap when
        there's no usable stop distance to size against (e.g. ATR unavailable
        yet) -- that cap is already conservative, so it's deliberately left
        unaffected by risk_multiplier."""
        max_position_value = run.cash * MAX_POSITION_ALLOCATION_FRACTION
        if stop_loss is None or stop_loss >= entry_price:
            return max_position_value
        risk_per_share = entry_price - stop_loss
        risk_budget = run.cash * RISK_PER_TRADE_FRACTION * risk_multiplier
        position_value_from_risk = (risk_budget / risk_per_share) * entry_price
        return min(position_value_from_risk, max_position_value)

    def _sell(self, db: Session, run: SimulationRun, position: SimulationPosition, price: float, reason: str) -> None:
        net_price = price * (1 - TRANSACTION_COST_RATE)
        proceeds = position.quantity * net_price
        pnl = (net_price - position.average_price) * position.quantity
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

        peak_equity = max(run.peak_equity or 0.0, equity)
        drawdown_pct = (peak_equity - equity) / peak_equity * 100.0 if peak_equity > 0 else 0.0

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
            peak_equity=round(peak_equity, 2),
            drawdown_pct=round(drawdown_pct, 2),
            trading_paused=drawdown_pct >= MAX_DRAWDOWN_FRACTION * 100.0,
            stop_loss_pct=run.stop_loss_pct,
            take_profit_pct=run.take_profit_pct,
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
