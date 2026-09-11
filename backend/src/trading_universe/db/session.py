"""Engine and session management."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from trading_universe.db.models import Base
from trading_universe.settings import get_settings

_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None
_lock = threading.Lock()


def get_engine() -> Engine:
    global _engine, _factory
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is not None:
            return _engine
        url = get_settings().resolved_database_url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        engine = create_engine(url, future=True, connect_args=connect_args)

        if url.startswith("sqlite"):
            @event.listens_for(engine, "connect")
            def _sqlite_pragmas(dbapi_connection, _record):  # noqa: ANN001
                cursor = dbapi_connection.cursor()
                # WAL lets the scanner write while the API reads.
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        _engine = engine
        _factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        return _engine


def get_session() -> Session:
    get_engine()
    assert _factory is not None
    return _factory()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    Base.metadata.create_all(get_engine())


def reset_engine() -> None:
    """Drop the cached engine - used by tests."""
    global _engine, _factory
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _factory = None
