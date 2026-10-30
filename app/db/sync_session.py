"""Synchronous database session for Celery workers.

The FastAPI app talks to MySQL asynchronously (``app/db/session.py``), but Celery
tasks run in plain synchronous worker processes — and ``asyncio.run`` cannot be
used while the eager-mode task executes inside the request's event loop. Workers
therefore use this blocking engine (the same ``pymysql`` URL Alembic uses).
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

sync_engine = create_engine(settings.database_url_sync, pool_pre_ping=True, future=True)

SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False, class_=Session)


@contextmanager
def worker_session() -> Iterator[Session]:
    """Yield a session that commits on success and rolls back on error."""
    session = SyncSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
