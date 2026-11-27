"""Fixtures for tests that need a real Postgres.

Skips cleanly when no database is reachable, so `pytest` works on a laptop
without Docker running while still failing loudly in CI (where DATABASE_URL
is always set).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from gerry.store.schema import Base

DEFAULT_URL = "postgresql+psycopg://postgres:test@localhost:55432/gerry"


@pytest.fixture(scope="session")
def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    eng = create_engine(database_url, future=True)
    try:
        with eng.connect():
            pass
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"no Postgres at {database_url}: {exc}")
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session rolled back after each test, so tests stay isolated."""
    connection = engine.connect()
    transaction = connection.begin()
    sess = sessionmaker(bind=connection, future=True)()
    try:
        yield sess
    finally:
        sess.close()
        transaction.rollback()
        connection.close()
