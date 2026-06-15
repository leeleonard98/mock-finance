"""Shared pytest fixtures.

Tests run against the real Postgres `app_test` database (see Makefile::test
which auto-creates it). Each test uses a transactional rollback fixture so
inserts don't leak between tests.

Fixtures:
- test_engine    — session-scoped engine pointed at TEST_DATABASE_URL
- db             — function-scoped transactional session
- client         — async httpx client with overridden get_db
- mock_llm       — replaces app.llm.complete with a recording stub
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import app.llm as llm_module
from app.config import get_settings
from app.db import get_db
from app.main import app as fastapi_app
from app.models import Base


# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def test_engine() -> Iterator[Engine]:
    """Session-scoped engine pointing at TEST_DATABASE_URL.

    Schema is created via Base.metadata.create_all on entry and dropped on
    teardown. We deliberately do NOT run alembic in tests — feature dev
    shouldn't be blocked by a migration just to run tests. Migrations get
    exercised by `make migrate` against the dev DB.
    """
    settings = get_settings()
    engine = create_engine(settings.TEST_DATABASE_URL, pool_pre_ping=True, future=True)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def db(test_engine: Engine) -> Iterator[Session]:
    """Function-scoped transactional session.

    Standard SQLAlchemy 'transactional tests' pattern: open a connection,
    begin an outer transaction, bind a Session to it, yield, roll back.
    Each test sees a clean DB; nothing leaks.
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    TestingSessionLocal = sessionmaker(
        bind=connection, autocommit=False, autoflush=False, future=True
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(db: Session) -> AsyncIterator[httpx.AsyncClient]:
    """Async client wired to the FastAPI app via ASGITransport.

    Overrides get_db so requests use the per-test transactional session.
    """

    def _override_get_db() -> Iterator[Session]:
        yield db

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    transport = httpx.ASGITransport(app=fastapi_app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        fastapi_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# LLM mock — single-turn complete()
# ---------------------------------------------------------------------------


class MockLLM:
    """Records calls to complete() and returns a configurable string."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.return_value: str | None = None

    def __call__(
        self, prompt: str, *, model: str | None = None, system: str | None = None
    ) -> str:
        self.calls.append({"prompt": prompt, "model": model, "system": system})
        if self.return_value is not None:
            return self.return_value
        return f"MOCK: {prompt}"[:200]


@pytest.fixture
def mock_llm(monkeypatch: pytest.MonkeyPatch) -> Iterator[MockLLM]:
    """Monkeypatch app.llm.complete with a recording stub."""
    mock = MockLLM()
    monkeypatch.setattr(llm_module, "complete", mock)
    yield mock
