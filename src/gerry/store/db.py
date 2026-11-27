"""Database session management. Thin I/O boundary."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from gerry.store.schema import Base

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def init_engine(database_url: str, *, create: bool = False) -> Engine:
    """Create the engine once per process."""
    global _engine, _SessionFactory
    _engine = create_engine(database_url, future=True, pool_pre_ping=True)
    _SessionFactory = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    if create:
        Base.metadata.create_all(_engine)
        logger.info("schema ensured")
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on failure."""
    if _SessionFactory is None:
        raise RuntimeError("init_engine() must be called before session_scope()")
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
