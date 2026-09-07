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
    assert status.cash == pytest.approx(10_000.0 * 0.8)  # 20% allocated


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
