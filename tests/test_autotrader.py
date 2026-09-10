from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.autotrader.autotrader_service import (
    AutoTraderService,
    AVOID_EXIT_STREAK_REQUIRED,
    BIST_MAX_DRAWDOWN_FRACTION,
    FIXED_PCT_TP2_RATIO,
    MAX_CONCURRENT_POSITIONS,
    MAX_DRAWDOWN_FRACTION,
    MIN_RELEVANT_HEADLINES_FOR_NEWS_GATE,
    TRANSACTION_COST_RATE,
    max_drawdown_fraction_for_market,
)
from app.autotrader.db_models import SimulationPosition, SimulationRun
from app.autotrader.models import StartSimulationRequest
from app.core.exceptions import RiskCalculationError
from app.fundamentals.models import LongTermOutlook, LongTermOutlookLabel
from app.macro.models import MacroIndicator
from app.news.models import NewsItem, SentimentLabel, SymbolNewsSummary
from app.risk.risk_engine import RiskAnalysis, RiskLevel
from app.signals.models import CategoryScores, DipConfidence, DipOpportunity, SignalResult, SignalType
from app.storage.database import Base, make_engine


class _FakeScannerService:
    """Minimal stand-in for ScannerService: AutoTraderService only calls
    get_signal() and get_scan_results(), so that's all we need to fake."""

    def __init__(self) -> None:
        self._signals: dict[str, SignalResult] = {}

    def set_signal(
        self, symbol: str, signal: SignalType, price: float, score: int = 80,
        stop_loss: float | None = None, take_profit_1: float | None = None,
        take_profit_2: float | None = None,
        daily_trend_up: bool | None = None, dip_confidence: DipConfidence | None = None,
    ) -> None:
        risk = None
        if stop_loss is not None:
            resolved_tp1 = take_profit_1 or price * 1.1
            risk = RiskAnalysis(
                entry_price=price, stop_loss=stop_loss, take_profit_1=resolved_tp1,
                take_profit_2=take_profit_2 or resolved_tp1 * 1.1, atr=1.0, risk_per_share=price - stop_loss,
                reward_per_share_tp1=resolved_tp1 - price, risk_reward_ratio=2.0,
                risk_level=RiskLevel.MEDIUM,
            )
        dip_opportunity = None
        if dip_confidence is not None:
            dip_opportunity = DipOpportunity(confidence=dip_confidence, reasons=[])
        self._signals[symbol] = SignalResult(
            symbol=symbol, price=price, score=score, signal=signal,
            reasons=[], risk_level=RiskLevel.MEDIUM,
            category_scores=CategoryScores(trend=score // 5, momentum=score // 5, volume=score // 5,
                                            price_action=score // 5, risk_reward=score // 5),
            risk_analysis=risk,
            daily_trend_up=daily_trend_up,
            dip_opportunity=dip_opportunity,
        )

    def get_signal(self, symbol: str) -> SignalResult | None:
        return self._signals.get(symbol.upper())

    def get_scan_results(self) -> list[SignalResult]:
        return list(self._signals.values())


class _FakeFundamentalsService:
    """Minimal stand-in for FundamentalsService: AutoTraderService only
    calls get_sector() and get_long_term_outlook()."""

    def __init__(self) -> None:
        self._sectors: dict[str, str] = {}
        self._outlooks: dict[str, LongTermOutlookLabel] = {}

    def set_sector(self, symbol: str, sector: str) -> None:
        self._sectors[symbol.upper()] = sector

    def get_sector(self, symbol: str) -> str | None:
        return self._sectors.get(symbol.upper())

    def set_outlook_label(self, symbol: str, label: LongTermOutlookLabel) -> None:
        self._outlooks[symbol.upper()] = label

    def get_long_term_outlook(self, symbol: str) -> LongTermOutlook:
        label = self._outlooks.get(symbol.upper(), LongTermOutlookLabel.NEUTRAL)
        return LongTermOutlook(symbol=symbol.upper(), label=label, score=50, reasons=[])


class _FakeMacroService:
    """Minimal stand-in for MacroService: AutoTraderService only calls
    get_indicators() and looks for "^VIX" in the result."""

    def __init__(self) -> None:
        self._vix: float | None = None

    def set_vix(self, price: float) -> None:
        self._vix = price

    def get_indicators(self) -> list[MacroIndicator]:
        if self._vix is None:
            return []
        return [MacroIndicator(symbol="^VIX", label="VIX", description="", price=self._vix, change_pct=None, as_of=None)]


class _FakeNewsService:
    """Minimal stand-in for NewsService: AutoTraderService only calls
    get_news(). set_news() computes overall the same way news_service.py's
    _summarize() does, so tests exercise the real majority-vote shape."""

    def __init__(self) -> None:
        self._summaries: dict[str, SymbolNewsSummary] = {}

    def set_news(self, symbol: str, items: list[NewsItem]) -> None:
        positive = sum(1 for i in items if i.sentiment == SentimentLabel.POSITIVE)
        negative = sum(1 for i in items if i.sentiment == SentimentLabel.NEGATIVE)
        neutral = sum(1 for i in items if i.sentiment == SentimentLabel.NEUTRAL)
        overall = (
            SentimentLabel.UNAVAILABLE if not items
            else SentimentLabel.NEGATIVE if negative > positive and negative >= neutral
            else SentimentLabel.POSITIVE if positive > negative and positive >= neutral
            else SentimentLabel.NEUTRAL
        )
        self._summaries[symbol.upper()] = SymbolNewsSummary(
            symbol=symbol.upper(), items=items, positive_count=positive,
            negative_count=negative, neutral_count=neutral, overall=overall,
        )

    def get_news(self, symbol: str) -> SymbolNewsSummary | None:
        return self._summaries.get(symbol.upper())


@pytest.fixture
def session_factory():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def scanner():
    return _FakeScannerService()


def _service(session_factory, scanner, fundamentals=None, macro=None, news=None, market="test") -> AutoTraderService:
    return AutoTraderService(
        session_factory=session_factory, market=market, currency_symbol="₺", scanner_service=scanner,
        fundamentals_service=fundamentals, macro_service=macro, news_service=news,
    )


def test_start_run_creates_running_simulation(session_factory, scanner):
    svc = _service(session_factory, scanner)
    status = svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    assert status.status.value == "RUNNING"
    assert status.cash == 10_000.0
    assert status.equity == 10_000.0


def test_start_run_rejects_when_already_running(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    with pytest.raises(RiskCalculationError):
        svc.start_run(initial_cash=5_000.0, duration_days=7.0)


def test_tick_buys_on_strong_signal(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, take_profit_1=110.0)

    svc._tick_sync()

    status = svc.get_status()
    assert status.trade_count == 1
    assert len(status.positions) == 1
    assert status.positions[0].symbol == "AAPL"
    # risk-based sizing wants (cash*2%)/risk_per_share*price = 4000 here,
    # which exceeds the flat 20% cap (2000) -- so it hits the cap instead.
    # Cash paid out also includes the buy-side transaction cost.
    assert status.cash == pytest.approx(10_000.0 - 2000.0 * (1 + TRANSACTION_COST_RATE))


def test_tick_sells_on_stop_loss_hit(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, take_profit_1=110.0)
    svc._tick_sync()  # buys AAPL

    scanner.set_signal("AAPL", SignalType.NEUTRAL, price=94.0, stop_loss=95.0, take_profit_1=110.0)
    svc._tick_sync()  # price fell through stop-loss -> should sell

    status = svc.get_status()
    assert len(status.positions) == 0
    assert status.trade_count == 2
    assert status.recent_trades[0].action == "SELL"
    assert "Zarar-kes" in status.recent_trades[0].reason
    assert status.realized_pnl is not None and status.realized_pnl < 0


def test_single_avoid_tick_does_not_sell(session_factory, scanner):
    """A lone noisy AVOID reading must not whipsaw the position out --
    see AVOID_EXIT_STREAK_REQUIRED."""
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=90.0, take_profit_1=110.0)
    svc._tick_sync()

    scanner.set_signal("AAPL", SignalType.AVOID, price=101.0, stop_loss=90.0, take_profit_1=110.0)
    svc._tick_sync()

    assert len(svc.get_status().positions) == 1


def test_tick_sells_when_signal_drops_to_avoid_for_the_required_streak(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=90.0, take_profit_1=110.0)
    svc._tick_sync()

    scanner.set_signal("AAPL", SignalType.AVOID, price=101.0, stop_loss=90.0, take_profit_1=110.0)
    for _ in range(AVOID_EXIT_STREAK_REQUIRED):
        svc._tick_sync()

    status = svc.get_status()
    assert len(status.positions) == 0
    assert "KAÇININ" in status.recent_trades[0].reason


def test_avoid_streak_resets_when_signal_recovers(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=90.0, take_profit_1=110.0)
    svc._tick_sync()

    for _ in range(AVOID_EXIT_STREAK_REQUIRED - 1):
        scanner.set_signal("AAPL", SignalType.AVOID, price=101.0, stop_loss=90.0, take_profit_1=110.0)
        svc._tick_sync()
    assert len(svc.get_status().positions) == 1  # not yet at the streak requirement

    scanner.set_signal("AAPL", SignalType.NEUTRAL, price=101.0, stop_loss=90.0, take_profit_1=110.0)
    svc._tick_sync()  # recovers -- resets the streak

    for _ in range(AVOID_EXIT_STREAK_REQUIRED - 1):
        scanner.set_signal("AAPL", SignalType.AVOID, price=101.0, stop_loss=90.0, take_profit_1=110.0)
        svc._tick_sync()

    assert len(svc.get_status().positions) == 1  # streak restarted, still hasn't reached the requirement again


def test_max_concurrent_positions_respected(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    for i in range(MAX_CONCURRENT_POSITIONS + 3):
        scanner.set_signal(f"SYM{i}", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0)

    svc._tick_sync()

    status = svc.get_status()
    assert len(status.positions) == MAX_CONCURRENT_POSITIONS


def test_run_closes_and_liquidates_after_duration_expires(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, take_profit_1=110.0)
    svc._tick_sync()

    # Force the run into the past so the next tick sees it as expired.
    with session_factory() as db:
        run = db.query(SimulationRun).filter(SimulationRun.market == "test").one()
        run.ends_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        db.commit()

    scanner.set_signal("AAPL", SignalType.NEUTRAL, price=105.0, stop_loss=95.0, take_profit_1=110.0)
    svc._tick_sync()

    status = svc.get_status()
    assert status.status.value == "COMPLETED"
    assert len(status.positions) == 0
    assert status.realized_pnl is not None and status.realized_pnl > 0  # bought at 100, closed at 105


def test_no_active_run_status_is_not_started(session_factory, scanner):
    svc = _service(session_factory, scanner)
    status = svc.get_status()
    assert status.status.value == "NOT_STARTED"


def test_stop_run_liquidates_positions_and_completes(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, take_profit_1=200.0)
    svc._tick_sync()  # buys AAPL
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=105.0, stop_loss=95.0, take_profit_1=200.0)

    status = svc.stop_run()

    assert status.status.value == "COMPLETED"
    assert len(status.positions) == 0
    assert status.recent_trades[0].action == "SELL"
    assert "Kullanıcı tarafından durduruldu" in status.recent_trades[0].reason
    assert status.realized_pnl is not None and status.realized_pnl > 0  # bought at 100, closed at 105

    # a stopped run is done -- a subsequent tick must be a no-op, not resume it
    svc._tick_sync()
    assert svc.get_status().status.value == "COMPLETED"


def test_stop_run_without_active_run_raises(session_factory, scanner):
    svc = _service(session_factory, scanner)
    with pytest.raises(RiskCalculationError):
        svc.stop_run()


def test_stop_run_allows_starting_a_new_simulation(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    svc.stop_run()

    status = svc.start_run(initial_cash=5_000.0, duration_days=3.0)
    assert status.status.value == "RUNNING"
    assert status.cash == 5_000.0


def test_position_sizing_scales_inversely_with_stop_distance(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    # Tight stop (risk_per_share=5) -- risk-based sizing wants 4000, capped
    # at the flat 20% (2000 of the 10,000 starting cash).
    scanner.set_signal("TIGHT", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)
    # Wide stop (risk_per_share=20, i.e. more volatile) -- risk-based sizing
    # wants a smaller position, well under the cap either way.
    scanner.set_signal("WIDE", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=80.0, score=80)

    svc._tick_sync()

    status = svc.get_status()
    positions = {p.symbol: p for p in status.positions}
    # TIGHT is processed first (higher score), sized against the full 10,000.
    # (quantity is sized off the raw allocation/price -- the transaction
    # cost only changes how much cash is actually paid out, not this.)
    assert positions["TIGHT"].quantity * 100.0 == pytest.approx(2000.0)
    # WIDE is processed second, against whatever cash TIGHT's purchase left
    # behind -- which is slightly less than a naive 8,000 because TIGHT's
    # cash outlay included its own transaction cost.
    remaining_cash = 10_000.0 - 2000.0 * (1 + TRANSACTION_COST_RATE)
    expected_wide_value = (remaining_cash * 0.02 / 20.0) * 100.0
    assert positions["WIDE"].quantity * 100.0 == pytest.approx(expected_wide_value)


def test_position_sizing_falls_back_to_flat_cap_without_a_stop(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0)  # no stop_loss given

    svc._tick_sync()

    status = svc.get_status()
    assert status.positions[0].quantity * 100.0 == pytest.approx(2000.0)  # flat 20% cap


def test_trailing_stop_ratchets_up_as_price_rises(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, take_profit_1=200.0)
    svc._tick_sync()  # buys at 100, initial stop=95

    # Price rises well past entry -- the fake's ATR is 1.0, so the trailing
    # candidate is 110 - 1.5*1.0 = 108.5, above the original 95.
    scanner.set_signal("AAPL", SignalType.BUY_SETUP, price=110.0, stop_loss=95.0, take_profit_1=200.0)
    svc._tick_sync()

    status = svc.get_status()
    assert len(status.positions) == 1
    assert status.positions[0].stop_loss == pytest.approx(108.5)


def test_sector_cap_blocks_third_position_in_same_sector(session_factory, scanner):
    fundamentals = _FakeFundamentalsService()
    for sym in ("A", "B", "C"):
        fundamentals.set_sector(sym, "Technology")
    svc = _service(session_factory, scanner, fundamentals=fundamentals)
    svc.start_run(initial_cash=100_000.0, duration_days=7.0)
    for sym in ("A", "B", "C"):
        scanner.set_signal(sym, SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)

    svc._tick_sync()

    status = svc.get_status()
    assert len(status.positions) == 2  # capped at MAX_POSITIONS_PER_SECTOR (2)


def test_sector_cap_allows_other_sectors_once_one_is_full(session_factory, scanner):
    fundamentals = _FakeFundamentalsService()
    fundamentals.set_sector("A", "Technology")
    fundamentals.set_sector("B", "Technology")
    fundamentals.set_sector("C", "Technology")
    fundamentals.set_sector("D", "Healthcare")
    svc = _service(session_factory, scanner, fundamentals=fundamentals)
    svc.start_run(initial_cash=100_000.0, duration_days=7.0)
    for sym in ("A", "B", "C", "D"):
        scanner.set_signal(sym, SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)

    svc._tick_sync()

    bought = {p.symbol for p in svc.get_status().positions}
    assert bought == {"A", "B", "D"}  # C is the 3rd Technology candidate -> blocked


def test_sector_cap_not_applied_without_a_fundamentals_service(session_factory, scanner):
    svc = _service(session_factory, scanner)  # no fundamentals_service -> no sector data at all
    svc.start_run(initial_cash=100_000.0, duration_days=7.0)
    for sym in ("A", "B", "C"):
        scanner.set_signal(sym, SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)

    svc._tick_sync()

    assert len(svc.get_status().positions) == 3


def test_dip_opportunity_triggers_entry_without_a_trend_buy_setup(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal(
        "AAPL", SignalType.NEUTRAL, price=100.0, stop_loss=95.0, score=30,  # comfortably below any reasonable AUTOTRADER_ENTRY_SCORE_MIN
        dip_confidence=DipConfidence.STRONG,
    )

    svc._tick_sync()

    status = svc.get_status()
    assert len(status.positions) == 1
    assert status.positions[0].symbol == "AAPL"
    assert "Dip Fırsatı" in status.recent_trades[0].reason


def test_medium_dip_confidence_does_not_trigger_an_entry(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal(
        "AAPL", SignalType.NEUTRAL, price=100.0, stop_loss=95.0, score=30,  # comfortably below any reasonable AUTOTRADER_ENTRY_SCORE_MIN
        dip_confidence=DipConfidence.MEDIUM,
    )

    svc._tick_sync()

    assert len(svc.get_status().positions) == 0


def test_trend_candidates_take_priority_over_dip_candidates_for_limited_slots(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=100_000.0, duration_days=7.0)
    for i in range(MAX_CONCURRENT_POSITIONS):
        scanner.set_signal(f"TREND{i}", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)
    scanner.set_signal(
        "DIP", SignalType.NEUTRAL, price=100.0, stop_loss=95.0, score=30, dip_confidence=DipConfidence.STRONG
    )

    svc._tick_sync()

    symbols = {p.symbol for p in svc.get_status().positions}
    assert "DIP" not in symbols  # all 5 slots already claimed by trend candidates


def test_position_size_reduced_when_vix_elevated(session_factory, scanner):
    macro = _FakeMacroService()
    macro.set_vix(35.0)  # >= high threshold -> 0.25x risk
    svc = _service(session_factory, scanner, macro=macro)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)

    svc._tick_sync()

    status = svc.get_status()
    # risk_budget = 10000*2%*0.25 = 50; quantity = 50/5 = 10; value = 1000 (well under the 2000 cap).
    assert status.positions[0].quantity * 100.0 == pytest.approx(1000.0)


def test_position_size_unaffected_when_vix_calm(session_factory, scanner):
    macro = _FakeMacroService()
    macro.set_vix(12.0)  # below the elevated threshold
    svc = _service(session_factory, scanner, macro=macro)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)

    svc._tick_sync()

    status = svc.get_status()
    assert status.positions[0].quantity * 100.0 == pytest.approx(2000.0)  # flat 20% cap, same as no-VIX case


def test_position_size_unaffected_without_a_macro_service(session_factory, scanner):
    svc = _service(session_factory, scanner)  # no macro_service -> no VIX data at all
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)

    svc._tick_sync()

    status = svc.get_status()
    assert status.positions[0].quantity * 100.0 == pytest.approx(2000.0)


def test_entry_skipped_when_daily_trend_is_confirmed_down(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal(
        "AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90, daily_trend_up=False
    )

    svc._tick_sync()

    assert len(svc.get_status().positions) == 0


def test_entry_allowed_when_daily_trend_is_unknown(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal(
        "AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90, daily_trend_up=None
    )

    svc._tick_sync()

    assert len(svc.get_status().positions) == 1


def test_dip_entry_skipped_when_daily_trend_is_confirmed_down(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal(
        "AAPL", SignalType.NEUTRAL, price=100.0, stop_loss=95.0, score=30,  # comfortably below any reasonable AUTOTRADER_ENTRY_SCORE_MIN
        dip_confidence=DipConfidence.STRONG, daily_trend_up=False,
    )

    svc._tick_sync()

    assert len(svc.get_status().positions) == 0


def test_long_term_outlook_unfavorable_blocks_entry(session_factory, scanner):
    fundamentals = _FakeFundamentalsService()
    fundamentals.set_outlook_label("AAPL", LongTermOutlookLabel.UNFAVORABLE)
    svc = _service(session_factory, scanner, fundamentals=fundamentals)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)

    svc._tick_sync()

    assert len(svc.get_status().positions) == 0


def test_long_term_outlook_neutral_or_unset_allows_entry(session_factory, scanner):
    fundamentals = _FakeFundamentalsService()
    fundamentals.set_outlook_label("AAPL", LongTermOutlookLabel.NEUTRAL)
    svc = _service(session_factory, scanner, fundamentals=fundamentals)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)

    svc._tick_sync()

    assert len(svc.get_status().positions) == 1


def test_long_term_outlook_favorable_allows_entry_and_unfavorable_still_blocks(session_factory, scanner):
    fundamentals = _FakeFundamentalsService()
    fundamentals.set_outlook_label("GOOD", LongTermOutlookLabel.FAVORABLE)
    fundamentals.set_outlook_label("BAD", LongTermOutlookLabel.UNFAVORABLE)
    svc = _service(session_factory, scanner, fundamentals=fundamentals)
    svc.start_run(initial_cash=100_000.0, duration_days=7.0)
    scanner.set_signal("GOOD", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)
    scanner.set_signal("BAD", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)

    svc._tick_sync()

    bought = {p.symbol for p in svc.get_status().positions}
    assert bought == {"GOOD"}


def _negative_items(count: int, mention_company: bool) -> list[NewsItem]:
    title = "Apple shares slide on weak demand" if mention_company else "Dow Jones Futures Fall As Oil Prices Rise"
    return [NewsItem(title=f"{title} ({i})", sentiment=SentimentLabel.NEGATIVE) for i in range(count)]


def test_news_sentiment_allowed_without_a_news_service(session_factory, scanner):
    svc = _service(session_factory, scanner)  # no news_service at all
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)

    svc._tick_sync()

    assert len(svc.get_status().positions) == 1


def test_news_sentiment_allowed_when_no_cached_summary_for_symbol(session_factory, scanner):
    news = _FakeNewsService()  # never called set_news() for AAPL
    svc = _service(session_factory, scanner, news=news)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)

    svc._tick_sync()

    assert len(svc.get_status().positions) == 1


def test_news_sentiment_blocks_entry_when_confirmed_negative_after_filtering(session_factory, scanner):
    news = _FakeNewsService()
    news.set_news("AAPL", _negative_items(MIN_RELEVANT_HEADLINES_FOR_NEWS_GATE, mention_company=True))
    svc = _service(session_factory, scanner, news=news)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)

    svc._tick_sync()

    assert len(svc.get_status().positions) == 0


def test_news_sentiment_allows_entry_below_minimum_relevant_headline_count(session_factory, scanner):
    news = _FakeNewsService()
    thin_count = MIN_RELEVANT_HEADLINES_FOR_NEWS_GATE - 1
    news.set_news("AAPL", _negative_items(thin_count, mention_company=True))
    svc = _service(session_factory, scanner, news=news)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)

    svc._tick_sync()

    assert len(svc.get_status().positions) == 1  # too thin a sample to act on


def test_news_sentiment_allows_entry_when_negative_headlines_are_irrelevant(session_factory, scanner):
    news = _FakeNewsService()
    # Enough negative headlines to clear the count bar, but none of them
    # actually name Apple -- general market noise, exactly the empirically
    # observed problem this gate is designed around.
    news.set_news("AAPL", _negative_items(MIN_RELEVANT_HEADLINES_FOR_NEWS_GATE, mention_company=False))
    svc = _service(session_factory, scanner, news=news)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)

    svc._tick_sync()

    assert len(svc.get_status().positions) == 1


def test_news_sentiment_uses_unfiltered_summary_when_symbol_missing_from_alias_map(session_factory, scanner):
    news = _FakeNewsService()
    # "ZZZZ" has no entry in symbol_aliases.py -- falls back to the
    # unfiltered summary rather than skipping the gate outright.
    news.set_news("ZZZZ", _negative_items(MIN_RELEVANT_HEADLINES_FOR_NEWS_GATE, mention_company=False))
    svc = _service(session_factory, scanner, news=news)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("ZZZZ", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)

    svc._tick_sync()

    assert len(svc.get_status().positions) == 0


def test_drawdown_circuit_breaker_blocks_new_entries(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    # Simulate a run that has already drawn down past the breaker threshold.
    with session_factory() as db:
        run = db.query(SimulationRun).filter(SimulationRun.market == "test").one()
        run.peak_equity = 10_000.0
        run.cash = 10_000.0 * (1 - MAX_DRAWDOWN_FRACTION - 0.01)
        db.commit()
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)

    svc._tick_sync()

    assert len(svc.get_status().positions) == 0


def test_max_drawdown_fraction_for_market_gives_bist_a_wider_threshold():
    # A 3y backtest sweep (see the constant's comment in autotrader_service.py)
    # found the flat 10% breaker paused new BIST entries on 64% of trading
    # days, vs. 0% for Global -- BIST alone gets a wider, still-calibrated
    # threshold instead of a guessed one-size-fits-all number.
    assert max_drawdown_fraction_for_market("bist") == BIST_MAX_DRAWDOWN_FRACTION
    assert BIST_MAX_DRAWDOWN_FRACTION > MAX_DRAWDOWN_FRACTION
    assert max_drawdown_fraction_for_market("global") == MAX_DRAWDOWN_FRACTION
    assert max_drawdown_fraction_for_market("crypto") == MAX_DRAWDOWN_FRACTION


def test_drawdown_circuit_breaker_does_not_block_bist_within_its_wider_threshold(session_factory, scanner):
    svc = _service(session_factory, scanner, market="bist")
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    # Past the original 10% breaker, but still inside BIST's wider 20% one --
    # this drawdown must NOT block a new entry for this market.
    with session_factory() as db:
        run = db.query(SimulationRun).filter(SimulationRun.market == "bist").one()
        run.peak_equity = 10_000.0
        run.cash = 10_000.0 * (1 - MAX_DRAWDOWN_FRACTION - 0.01)
        db.commit()
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)

    svc._tick_sync()

    assert len(svc.get_status().positions) == 1


def test_drawdown_circuit_breaker_still_blocks_bist_past_its_own_threshold(session_factory, scanner):
    svc = _service(session_factory, scanner, market="bist")
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    with session_factory() as db:
        run = db.query(SimulationRun).filter(SimulationRun.market == "bist").one()
        run.peak_equity = 10_000.0
        run.cash = 10_000.0 * (1 - BIST_MAX_DRAWDOWN_FRACTION - 0.01)
        db.commit()
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, score=90)

    svc._tick_sync()

    assert len(svc.get_status().positions) == 0


def test_drawdown_circuit_breaker_does_not_block_existing_exits(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, take_profit_1=200.0)
    svc._tick_sync()  # buys AAPL while the breaker is inactive

    # Now force the breaker active AND hit AAPL's stop-loss in the same tick.
    with session_factory() as db:
        run = db.query(SimulationRun).filter(SimulationRun.market == "test").one()
        run.peak_equity = 50_000.0  # far above current equity -> breaker active
        db.commit()
    scanner.set_signal("AAPL", SignalType.NEUTRAL, price=94.0, stop_loss=95.0, take_profit_1=200.0)

    svc._tick_sync()

    status = svc.get_status()
    assert len(status.positions) == 0  # stop-loss exit still happened despite the breaker
    assert status.recent_trades[0].action == "SELL"


def test_status_reports_peak_equity_and_drawdown(session_factory, scanner):
    svc = _service(session_factory, scanner)
    status = svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    assert status.peak_equity == pytest.approx(10_000.0)
    assert status.drawdown_pct == pytest.approx(0.0)
    assert status.trading_paused is False

    with session_factory() as db:
        run = db.query(SimulationRun).filter(SimulationRun.market == "test").one()
        run.peak_equity = 10_000.0
        run.cash = 8_000.0  # 20% drawdown, well past the 10% breaker
        db.commit()

    status = svc.get_status()
    assert status.drawdown_pct == pytest.approx(20.0)
    assert status.trading_paused is True


def test_partial_profit_taking_sells_half_at_tp1_and_promotes_target_to_tp2(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal(
        "AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0,
        take_profit_1=110.0, take_profit_2=120.0,
    )
    svc._tick_sync()  # buys AAPL
    original_quantity = svc.get_status().positions[0].quantity

    scanner.set_signal(
        "AAPL", SignalType.BUY_SETUP, price=111.0, stop_loss=95.0,
        take_profit_1=110.0, take_profit_2=120.0,
    )
    svc._tick_sync()  # price >= TP1 -> partial exit

    status = svc.get_status()
    assert len(status.positions) == 1  # still open -- only half closed
    assert status.positions[0].quantity == pytest.approx(original_quantity / 2)
    assert status.positions[0].take_profit == pytest.approx(120.0)  # promoted to TP2
    assert status.recent_trades[0].action == "SELL"
    assert "Kısmi" in status.recent_trades[0].reason

    # A second tick at the same price must not partially exit again.
    svc._tick_sync()
    assert svc.get_status().positions[0].quantity == pytest.approx(original_quantity / 2)


def test_partial_profit_taking_remainder_closes_fully_at_promoted_target(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal(
        "AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0,
        take_profit_1=110.0, take_profit_2=120.0,
    )
    svc._tick_sync()  # buys AAPL

    scanner.set_signal(
        "AAPL", SignalType.BUY_SETUP, price=111.0, stop_loss=95.0,
        take_profit_1=110.0, take_profit_2=120.0,
    )
    svc._tick_sync()  # partial exit at TP1, remainder's target -> 120.0

    scanner.set_signal(
        "AAPL", SignalType.BUY_SETUP, price=121.0, stop_loss=95.0,
        take_profit_1=110.0, take_profit_2=120.0,
    )
    svc._tick_sync()  # price >= promoted target -> remainder fully closes

    status = svc.get_status()
    assert len(status.positions) == 0
    assert status.recent_trades[0].action == "SELL"
    assert "Kâr-al" in status.recent_trades[0].reason  # the normal full-exit path, not another partial


def test_no_partial_exit_for_a_position_without_take_profit_2(session_factory, scanner):
    """A position that predates this feature -- persisted with
    take_profit_2 = NULL, exactly what Database.ensure_columns() backfills
    for an already-running position -- must fall back to the old
    all-or-nothing exit at TP1 rather than erroring or getting stuck."""
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    with session_factory() as db:
        run = db.query(SimulationRun).filter(SimulationRun.market == "test").one()
        db.add(SimulationPosition(
            run_id=run.id, symbol="AAPL", quantity=10.0, average_price=100.0,
            stop_loss=95.0, take_profit=110.0, take_profit_2=None,
            opened_at=datetime.now(timezone.utc),
        ))
        db.commit()

    scanner.set_signal("AAPL", SignalType.BUY_SETUP, price=111.0, stop_loss=95.0, take_profit_1=110.0)
    svc._tick_sync()

    status = svc.get_status()
    assert len(status.positions) == 0
    assert "Kâr-al" in status.recent_trades[0].reason


def test_transaction_cost_reduces_round_trip_realized_pnl(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, take_profit_1=200.0)
    svc._tick_sync()  # buys at 100 -- cost basis becomes 100*(1+cost)
    quantity = svc.get_status().positions[0].quantity

    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, take_profit_1=200.0)
    status = svc.stop_run()  # sells at the same price with no price movement at all

    # With zero price movement, a frictionless round trip would net exactly
    # 0 pnl -- the cost model must make this trade a small net loss instead.
    expected_pnl = (100.0 * (1 - TRANSACTION_COST_RATE) - 100.0 * (1 + TRANSACTION_COST_RATE)) * quantity
    assert status.realized_pnl == pytest.approx(expected_pnl, abs=0.01)
    assert status.realized_pnl < 0


def test_trailing_stop_never_moves_down(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, take_profit_1=200.0)
    svc._tick_sync()  # buys at 100, stop=95

    scanner.set_signal("AAPL", SignalType.BUY_SETUP, price=110.0, stop_loss=95.0, take_profit_1=200.0)
    svc._tick_sync()  # stop trails up to 108.5

    # Price dips slightly but stays above the trailed stop (no exit).
    # Trailing candidate here would be 109 - 1.5 = 107.5, BELOW the
    # already-ratcheted 108.5 -- the stop must not move back down.
    scanner.set_signal("AAPL", SignalType.BUY_SETUP, price=109.0, stop_loss=95.0, take_profit_1=200.0)
    svc._tick_sync()

    status = svc.get_status()
    assert len(status.positions) == 1
    assert status.positions[0].stop_loss == pytest.approx(108.5)


def test_fixed_pct_mode_derives_stop_and_take_profit_from_entry_price(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0, stop_loss_pct=5.0, take_profit_pct=10.0)
    # ATR-derived values are deliberately way off (50/300) to prove the fixed
    # percentages -- not RiskEngine's numbers -- are what actually gets used.
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=50.0, take_profit_1=300.0)
    svc._tick_sync()

    status = svc.get_status()
    assert len(status.positions) == 1
    assert status.positions[0].stop_loss == pytest.approx(95.0)  # 100 * (1 - 5/100)
    assert status.positions[0].take_profit == pytest.approx(110.0)  # 100 * (1 + 10/100)


def test_fixed_pct_mode_derives_take_profit_2_using_fixed_ratio(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0, stop_loss_pct=5.0, take_profit_pct=10.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=50.0, take_profit_1=300.0)
    svc._tick_sync()

    # take_profit_2 isn't directly exposed on SimulationPositionOut -- verify
    # it via the partial-exit promotion (take_profit becomes TP2's value
    # once TP1 is hit), exercising the real code path instead of the DB.
    expected_tp2 = 100.0 * (1 + 10.0 * FIXED_PCT_TP2_RATIO / 100)
    scanner.set_signal("AAPL", SignalType.BUY_SETUP, price=111.0, stop_loss=50.0, take_profit_1=300.0)
    svc._tick_sync()  # price >= TP1 (110) -> partial exit, promotes target to TP2

    assert svc.get_status().positions[0].take_profit == pytest.approx(expected_tp2)


def test_fixed_pct_mode_trailing_stop_ratchets_up_as_percentage_of_price(session_factory, scanner):
    svc = _service(session_factory, scanner)
    # take_profit_pct=50 keeps TP1 (150) well above the prices used here, so
    # this test isolates the trailing-stop behavior from partial-exit.
    svc.start_run(initial_cash=10_000.0, duration_days=7.0, stop_loss_pct=5.0, take_profit_pct=50.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=1.0, take_profit_1=1000.0)
    svc._tick_sync()  # buys at 100, initial stop = 100*(1-0.05) = 95

    # Trailing candidate should be 5% below the NEW price (110*0.95=104.5),
    # not ATR-derived (the fake's stop_loss=1.0 would imply something wildly different).
    scanner.set_signal("AAPL", SignalType.BUY_SETUP, price=110.0, stop_loss=1.0, take_profit_1=1000.0)
    svc._tick_sync()

    assert svc.get_status().positions[0].stop_loss == pytest.approx(104.5)


def test_fixed_pct_mode_trailing_stop_never_moves_down(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0, stop_loss_pct=5.0, take_profit_pct=50.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=1.0, take_profit_1=1000.0)
    svc._tick_sync()  # stop = 95

    scanner.set_signal("AAPL", SignalType.BUY_SETUP, price=110.0, stop_loss=1.0, take_profit_1=1000.0)
    svc._tick_sync()  # stop trails to 104.5

    # Price dips slightly; trailing candidate here (108*0.95=102.6) is BELOW
    # the already-ratcheted 104.5 -- must not move back down.
    scanner.set_signal("AAPL", SignalType.BUY_SETUP, price=108.0, stop_loss=1.0, take_profit_1=1000.0)
    svc._tick_sync()

    assert svc.get_status().positions[0].stop_loss == pytest.approx(104.5)


def test_fixed_pct_mode_partial_profit_taking_still_works(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0, stop_loss_pct=5.0, take_profit_pct=10.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=1.0, take_profit_1=1000.0)
    svc._tick_sync()  # buys at 100; TP1 = 110
    original_quantity = svc.get_status().positions[0].quantity

    scanner.set_signal("AAPL", SignalType.BUY_SETUP, price=111.0, stop_loss=1.0, take_profit_1=1000.0)
    svc._tick_sync()  # price >= TP1 (110) -> partial exit

    status = svc.get_status()
    assert len(status.positions) == 1  # still open, only half closed
    assert status.positions[0].quantity == pytest.approx(original_quantity / 2)
    assert "Kısmi" in status.recent_trades[0].reason


def test_status_reports_none_for_stop_loss_pct_in_default_atr_mode(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)  # stop_loss_pct/take_profit_pct left unset

    status = svc.get_status()
    assert status.stop_loss_pct is None
    assert status.take_profit_pct is None


def test_status_reports_the_chosen_fixed_percentages(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0, stop_loss_pct=5.0, take_profit_pct=10.0)

    status = svc.get_status()
    assert status.stop_loss_pct == pytest.approx(5.0)
    assert status.take_profit_pct == pytest.approx(10.0)


@pytest.mark.parametrize("bad_cash", [-10_000.0, 0.0, float("nan"), float("inf")])
def test_start_simulation_request_rejects_non_positive_or_non_finite_initial_cash(bad_cash):
    # A non-positive initial_cash used to leave a run permanently stuck
    # "RUNNING" -- every position size fell below MIN_TRADE_VALUE, so it
    # never traded, and start_run() refuses a new run while one is active.
    with pytest.raises(ValidationError):
        StartSimulationRequest(initial_cash=bad_cash)


@pytest.mark.parametrize("bad_duration", [-1.0, 0.0, float("nan")])
def test_start_simulation_request_rejects_non_positive_duration(bad_duration):
    with pytest.raises(ValidationError):
        StartSimulationRequest(duration_days=bad_duration)


def test_start_simulation_request_rejects_zero_stop_loss_pct():
    # A 0% stop_loss_pct put the initial stop at the entry price itself,
    # force-closing every position one tick after it opened.
    with pytest.raises(ValidationError):
        StartSimulationRequest(stop_loss_pct=0.0, take_profit_pct=10.0)


def test_start_simulation_request_rejects_stop_loss_pct_without_take_profit_pct():
    # Only one of the pair set used to silently size entries off ATR while
    # trailing the stop at an unrelated fixed percentage (see
    # _update_trailing_stop's docstring).
    with pytest.raises(ValidationError):
        StartSimulationRequest(stop_loss_pct=5.0)
    with pytest.raises(ValidationError):
        StartSimulationRequest(take_profit_pct=10.0)


def test_start_simulation_request_accepts_both_fixed_percentages_or_neither():
    both = StartSimulationRequest(stop_loss_pct=5.0, take_profit_pct=10.0)
    assert both.stop_loss_pct == 5.0 and both.take_profit_pct == 10.0

    neither = StartSimulationRequest()
    assert neither.stop_loss_pct is None and neither.take_profit_pct is None


def test_trailing_stop_falls_back_to_atr_when_only_one_fixed_pct_is_set_on_the_run(session_factory, scanner):
    # The API model now rejects this combination, but a pre-existing/
    # hand-edited DB row could still have it -- _update_trailing_stop must
    # fall back to ATR sizing rather than trailing at stop_loss_pct alone,
    # unrelated to how the position was actually sized at entry.
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)  # both None
    with session_factory() as db:
        run = db.query(SimulationRun).filter(SimulationRun.market == "test").one()
        run.stop_loss_pct = 5.0  # take_profit_pct left None -- simulates a half-set row
        db.commit()

    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=95.0, take_profit_1=200.0)
    svc._tick_sync()  # buys at 100, ATR-based stop=95 (fake's ATR=1.0)

    scanner.set_signal("AAPL", SignalType.BUY_SETUP, price=110.0, stop_loss=95.0, take_profit_1=200.0)
    svc._tick_sync()  # ATR trailing candidate: 110 - 1.5*1.0 = 108.5 (NOT 110*0.95=104.5)

    assert svc.get_status().positions[0].stop_loss == pytest.approx(108.5)


def test_run_lock_is_a_real_threading_lock(session_factory, scanner):
    svc = _service(session_factory, scanner)
    assert isinstance(svc._run_lock, type(threading.Lock()))


def test_stop_run_blocks_while_the_lock_is_held_by_another_thread(scanner):
    # Deterministic (not timing-dependent): if the lock is genuinely held,
    # a concurrent stop_run() on another thread cannot possibly finish
    # until it's released -- this is exactly the race the lock closes (a
    # tick mid-commit racing a concurrent stop_run(), see
    # AutoTraderService.__init__'s _run_lock docstring).
    #
    # Needs its own StaticPool-backed engine rather than the shared
    # session_factory fixture: plain sqlite:///:memory: hands out a fresh,
    # empty in-memory database per connection, so a session opened from the
    # thread below wouldn't see the tables/rows the main thread created.
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)

    svc._run_lock.acquire()
    try:
        thread = threading.Thread(target=svc.stop_run)
        thread.start()
        thread.join(timeout=0.3)
        assert thread.is_alive(), "stop_run() must block while _run_lock is held elsewhere"
    finally:
        svc._run_lock.release()

    thread.join(timeout=2.0)
    assert not thread.is_alive(), "stop_run() must complete once the lock is released"
    assert svc.get_status().status.value == "COMPLETED"
