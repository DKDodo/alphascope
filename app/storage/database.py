"""SQLAlchemy engine/session setup. Defaults to a local SQLite file so the
app runs with zero external database setup; point DATABASE_URL at Postgres
in production without changing any application code.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args)


def make_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Database:
    def __init__(self, database_url: str) -> None:
        self.engine = make_engine(database_url)
        self.session_factory = make_session_factory(self.engine)

    def create_all(self) -> None:
        Base.metadata.create_all(bind=self.engine)

    def ensure_columns(self, table_name: str, columns: dict[str, str]) -> None:
        """SQLite-only lightweight migration: create_all() only creates
        brand-new tables, it never alters one that already exists on disk.
        This is what lets a table with rows already in it (e.g. a running
        AutoTrader simulation) pick up new optional columns added to its
        model without losing any persisted data. No-op on a fresh DB
        (create_all already gave the table every current column) and on a
        non-SQLite backend (a Postgres switch would need its own migration
        tooling, out of scope here). `columns` maps column name to its SQL
        type/DEFAULT clause, e.g. {"peak_equity": "FLOAT DEFAULT 0.0"} --
        include a DEFAULT so SQLite backfills existing rows with a sane
        value instead of leaving them NULL.
        """
        if not self.engine.url.get_backend_name().startswith("sqlite"):
            return
        with self.engine.connect() as conn:
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table_name})"))}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {ddl}"))
            conn.commit()

    def session(self) -> Iterator[Session]:
        db = self.session_factory()
        try:
            yield db
        finally:
            db.close()
