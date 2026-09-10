from __future__ import annotations

from sqlalchemy import text

from app.autotrader import db_models  # noqa: F401 -- registers tables with Base.metadata
from app.storage.database import Database


def test_ensure_columns_adds_missing_column_and_preserves_existing_rows(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(f"sqlite:///{db_path}")

    # Simulate a table that already existed (with a row in it -- an
    # "already running simulation") before peak_equity was added to the model.
    with db.engine.connect() as conn:
        conn.execute(text("CREATE TABLE simulation_runs (id INTEGER PRIMARY KEY, market TEXT, cash FLOAT)"))
        conn.execute(text("INSERT INTO simulation_runs (id, market, cash) VALUES (1, 'test', 12345.0)"))
        conn.commit()

    db.ensure_columns("simulation_runs", {"peak_equity": "FLOAT DEFAULT 0.0"})

    with db.engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(simulation_runs)"))}
        assert "peak_equity" in columns

        row = conn.execute(text("SELECT market, cash, peak_equity FROM simulation_runs WHERE id = 1")).one()
        assert row.market == "test"
        assert row.cash == 12345.0  # pre-existing data untouched
        assert row.peak_equity == 0.0  # backfilled via the DEFAULT clause, not left NULL


def test_ensure_columns_is_a_noop_when_column_already_exists(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(f"sqlite:///{db_path}")
    with db.engine.connect() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, x FLOAT DEFAULT 0.0)"))
        conn.commit()

    db.ensure_columns("t", {"x": "FLOAT DEFAULT 0.0"})  # must not raise "duplicate column"

    with db.engine.connect() as conn:
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(t)"))]
        assert columns.count("x") == 1


def test_ensure_columns_noop_on_a_freshly_created_table():
    db = Database("sqlite:///:memory:")
    db.create_all()
    # create_all() already gave simulation_runs/simulation_positions every
    # current model column -- must not error trying to add them again.
    db.ensure_columns("simulation_runs", {"peak_equity": "FLOAT DEFAULT 0.0"})
    db.ensure_columns(
        "simulation_positions", {"take_profit_2": "FLOAT", "partial_exit_done": "INTEGER DEFAULT 0"}
    )


def test_sqlite_engine_uses_wal_journal_mode(tmp_path):
    # The scanner, AutoTrader, news and fundamentals services all write to
    # this one file concurrently from different threads -- WAL lets readers
    # proceed while a writer holds it, instead of blocking behind SQLite's
    # default rollback-journal lock.
    db_path = tmp_path / "wal_test.db"
    db = Database(f"sqlite:///{db_path}")
    with db.engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()
    assert mode.lower() == "wal"
