"""Database session management. Thin I/O boundary."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
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


def wait_for_database(engine: Engine, *, attempts: int = 6, delay: float = 3.0) -> bool:
    """Block until the database answers, or give up. Side-effecting.

    Fly stops idle Postgres machines; with autostart enabled a connection
    wakes one, but the boot takes ~20s and requests during that window would
    otherwise 500. Retrying turns a cold start into a slow request rather
    than an error.
    """
    for attempt in range(1, attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            if attempt > 1:
                logger.info("database answered after %d attempts", attempt)
            return True
        except OperationalError as exc:
            if attempt == attempts:
                logger.error("database unreachable after %d attempts: %s", attempts, exc)
                return False
            logger.warning(
                "database not ready (attempt %d/%d), waiting %.0fs", attempt, attempts, delay
            )
            time.sleep(delay)
    return False


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
