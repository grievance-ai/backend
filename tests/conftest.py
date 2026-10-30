"""Shared pytest fixtures."""

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any

from app.core.config import settings
from sqlalchemy.engine import make_url

# Point the suite at its own database and Redis index *before* anything imports
# app.db.session (which builds its engine from settings at import time), so
# tests never write into the dev data.
_TEST_DB_SUFFIX = "_test"
_dev_db = make_url(settings.database_url).database or "xuanwu"
_TEST_DB = _dev_db if _dev_db.endswith(_TEST_DB_SUFFIX) else _dev_db + _TEST_DB_SUFFIX
settings.database_url = (
    make_url(settings.database_url).set(database=_TEST_DB).render_as_string(hide_password=False)
)
settings.database_url_sync = (
    make_url(settings.database_url_sync)
    .set(database=_TEST_DB)
    .render_as_string(hide_password=False)
)
settings.redis_url = settings.redis_url.rsplit("/", 1)[0] + "/15"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
import redis.asyncio as redis  # noqa: E402
from app.api.deps import get_redis  # noqa: E402
from app.db.seeds import seed_levels, seed_permissions  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User  # noqa: E402
from fakeredis import FakeAsyncRedis  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from tests.factories import PASSWORD, UserFactory  # noqa: E402

_SEEDED_ROLES = ("superadmin", "admin", "member", "guest", "citizen", "officer")
_IDENTITY = "/api/v2/xuanwu/identity"

# Callable fixture aliases (a factory-builder and a login helper).
MakeUser = Callable[..., Awaitable[User]]
LoginAs = Callable[..., Awaitable[tuple[User, str]]]


@pytest.fixture(autouse=True)
def _eager_celery() -> None:
    """Run Celery tasks inline (no broker/worker) so audit/email work happens in-test."""
    from app.workers.celery_app import celery_app

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True


@pytest.fixture(autouse=True)
def _mock_email() -> None:
    """Capture outgoing email in memory and reset the outbox between tests."""
    from app.core.config import settings
    from app.integrations.email import mock

    settings.email_provider = "mock"
    mock.clear()


@pytest.fixture(autouse=True)
def _mock_sms() -> None:
    """Capture outgoing SMS in memory and reset the outbox between tests."""
    from app.core.config import settings
    from app.integrations.sms import mock

    settings.sms_provider = "mock"
    mock.clear()


@pytest.fixture(autouse=True)
def _mock_llm() -> None:
    """Never call a real LLM in tests; reset queued replies between tests."""
    from app.integrations.llm import mock

    settings.llm_provider = "mock"
    mock.clear()


@pytest.fixture(autouse=True)
def _mock_stt() -> None:
    """Never call a real speech-to-text service in tests; reset queued transcripts."""
    from app.integrations.stt import mock

    settings.stt_provider = "mock"
    mock.clear()


@pytest.fixture(autouse=True)
def _mock_tts() -> None:
    """Never call a real text-to-speech service in tests."""
    from app.integrations.tts import mock

    settings.tts_provider = "mock"
    mock.clear()


@pytest.fixture(autouse=True)
def _mock_embeddings() -> None:
    """Never call a real embedding service in tests."""
    settings.embedding_provider = "mock"


@pytest.fixture(autouse=True)
def _mock_websearch() -> None:
    """Never search the real web in tests; nothing is found unless a test queues it."""
    from app.integrations.websearch import mock as websearch_mock

    settings.websearch_provider = "mock"
    websearch_mock.reset()


@pytest.fixture(autouse=True)
def _local_storage(tmp_path: object) -> None:
    """Store uploads under a throwaway temp directory, not the repo tree."""
    from app.core.config import settings

    settings.storage_provider = "local"
    settings.upload_dir = str(tmp_path)


@pytest.fixture(autouse=True)
def _no_rate_limit() -> None:
    """Disable the global rate limiter so the suite isn't throttled."""
    from app.core.ratelimit import limiter

    limiter.enabled = False


@pytest.fixture
def fake_redis() -> redis.Redis:
    """An in-memory async Redis, so Redis-backed logic is unit-testable offline."""
    return FakeAsyncRedis(decode_responses=True)


@pytest.fixture(scope="session", autouse=True)
def _migrate_test_db() -> Iterator[None]:
    """Create the test database if needed and migrate it to head, once per run."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    server = make_url(settings.database_url_sync).set(database="")
    try:
        sync_engine = create_engine(server, poolclass=NullPool)
        with sync_engine.connect() as conn:
            conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{_TEST_DB}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
        sync_engine.dispose()
    except Exception:
        yield  # no database reachable: integration tests skip via ``_engine``
        return
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest_asyncio.fixture
async def _engine() -> AsyncIterator[AsyncEngine]:
    """A per-test engine (own event loop). Skips when no database is reachable."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        await engine.dispose()
        pytest.skip("requires a running database")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session for arranging test data, sharing the client's engine."""
    async with async_sessionmaker(_engine, expire_on_commit=False)() as session:
        yield session


@pytest_asyncio.fixture
async def client(_engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    """HTTP client wired to the app with per-test DB + Redis and seeded RBAC."""
    session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    test_redis: redis.Redis = redis.from_url(  # type: ignore[no-untyped-call]
        settings.redis_url, decode_responses=True
    )
    async with session_factory() as setup_session:
        await seed_permissions(setup_session)
        await seed_levels(setup_session)
    for role in _SEEDED_ROLES:
        await test_redis.delete(f"permissions:{role}")

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    async def _override_get_redis() -> redis.Redis:
        return test_redis

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis] = _override_get_redis
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            yield http_client
    finally:
        app.dependency_overrides.clear()
        await test_redis.aclose()


@pytest.fixture
def make_user(db: AsyncSession) -> MakeUser:
    """Build a user with ``UserFactory`` and persist it via the test session."""

    async def _make(**kwargs: Any) -> User:
        user: User = UserFactory.build(**kwargs)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    return _make


@pytest.fixture
def login_as(client: AsyncClient, make_user: MakeUser) -> LoginAs:
    """Create a user of the given role/state, log in, and return ``(user, csrf)``."""

    async def _login(
        role: str = "member", state: str = "active", **kwargs: Any
    ) -> tuple[User, str]:
        user = await make_user(role=role, state=state, **kwargs)
        resp = await client.post(
            f"{_IDENTITY}/sessions", json={"email": user.email, "password": PASSWORD}
        )
        assert resp.status_code == 200, resp.text
        return user, str(resp.json()["data"]["csrf_token"])

    return _login
