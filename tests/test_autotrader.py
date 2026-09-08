from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.autotrader.autotrader_service import AutoTraderService, MAX_CONCURRENT_POSITIONS
from app.autotrader.db_models import SimulationPosition, SimulationRun
from app.core.exceptions import RiskCalculationError
from app.risk.risk_engine import RiskAnalysis, RiskLevel
from app.signals.models import CategoryScores, SignalResult, SignalType
from app.storage.database import Base, make_engine


class _FakeScannerService:
    """Minimal stand-in for ScannerService: AutoTraderService only calls
    get_signal() and get_scan_results(), so that's all we need to fake."""

    def __init__(self) -> None:
        self._signals: dict[str, SignalResult] = {}

    def set_signal(self, symbol: str, signal: SignalType, price: float, score: int = 80,
                    stop_loss: float | None = None, take_profit_1: float | None = None) -> None:
        risk = None
        if stop_loss is not None:
            risk = RiskAnalysis(
                entry_price=price, stop_loss=stop_loss, take_profit_1=take_profit_1 or price * 1.1,
                take_profit_2=take_profit_1 or price * 1.2, atr=1.0, risk_per_share=price - stop_loss,
                reward_per_share_tp1=(take_profit_1 or price * 1.1) - price, risk_reward_ratio=2.0,
                risk_level=RiskLevel.MEDIUM,
            )
        self._signals[symbol] = SignalResult(
            symbol=symbol, price=price, score=score, signal=signal,
            reasons=[], risk_level=RiskLevel.MEDIUM,
            category_scores=CategoryScores(trend=score // 5, momentum=score // 5, volume=score // 5,
                                            price_action=score // 5, risk_reward=score // 5),
            risk_analysis=risk,
        )

    def get_signal(self, symbol: str) -> SignalResult | None:
        return self._signals.get(symbol.upper())

    def get_scan_results(self) -> list[SignalResult]:
        return list(self._signals.values())


@pytest.fixture
def session_factory():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def scanner():
    return _FakeScannerService()


def _service(session_factory, scanner) -> AutoTraderService:
    return AutoTraderService(
        session_factory=session_factory, market="test", currency_symbol="₺", scanner_service=scanner,
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
    assert status.cash == pytest.approx(10_000.0 * 0.8)


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


def test_tick_sells_when_signal_drops_to_avoid(session_factory, scanner):
    svc = _service(session_factory, scanner)
    svc.start_run(initial_cash=10_000.0, duration_days=7.0)
    scanner.set_signal("AAPL", SignalType.STRONG_BUY_SETUP, price=100.0, stop_loss=90.0, take_profit_1=110.0)
    svc._tick_sync()

    scanner.set_signal("AAPL", SignalType.AVOID, price=101.0, stop_loss=90.0, take_profit_1=110.0)
    svc._tick_sync()

    status = svc.get_status()
    assert len(status.positions) == 0
    assert "KAÇININ" in status.recent_trades[0].reason


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
    assert positions["TIGHT"].quantity * 100.0 == pytest.approx(2000.0)
    # WIDE is processed second, against the remaining 8,000 cash: risk_budget
    # = 8000*2% = 160, quantity = 160/20 = 8, value = 800 -- a much smaller
    # position than TIGHT's, because it's more volatile (wider stop).
    assert positions["WIDE"].quantity * 100.0 == pytest.approx(800.0)


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
