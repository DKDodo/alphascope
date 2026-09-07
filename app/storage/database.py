"""SQLAlchemy engine/session setup. Defaults to a local SQLite file so the
app runs with zero external database setup; point DATABASE_URL at Postgres
in production without changing any application code.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
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

    def session(self) -> Iterator[Session]:
        db = self.session_factory()
        try:
            yield db
        finally:
            db.close()
