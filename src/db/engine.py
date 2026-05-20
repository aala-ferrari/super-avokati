"""SQLAlchemy engine + session helpers for the legal knowledge base.

The engine is built lazily so importing this module doesn't require a
running Postgres — useful for tests and for the Flask app when the KB
happens to be down.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.config import LEGALKB_URL

_engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def engine() -> Engine:
    """Return a singleton SQLAlchemy engine bound to LEGALKB_URL."""
    global _engine, SessionLocal
    if _engine is None:
        _engine = create_engine(
            LEGALKB_URL,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            echo=False,
            future=True,
        )
        SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session scope. Commits on success, rolls back on error."""
    engine()  # initializes SessionLocal
    assert SessionLocal is not None
    sess = SessionLocal()
    try:
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()
