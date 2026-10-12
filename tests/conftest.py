import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)

from payment_service.api.main import app
from payment_service.config import settings
from payment_service.db import get_session
from payment_service.models import Base

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://payments:payments@localhost:5432/payments_test",
)

# A safety check against accidentally running tests against the development DB.
database_name = make_url(TEST_DATABASE_URL).database
if not database_name or not database_name.endswith("_test"):
    raise RuntimeError(
        "TEST_DATABASE_URL must point to a database whose name ends with '_test'.",
    )


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Use a predictable API key without depending on the local .env."""

    test_key = "test-api-key"
    monkeypatch.setattr(settings, "api_key", SecretStr(test_key))
    return test_key


@pytest_asyncio.fixture
async def test_engine() -> AsyncIterator[AsyncEngine]:
    """Create an isolated schema for each test."""

    engine = create_async_engine(
        TEST_DATABASE_URL,
        pool_pre_ping=True,
    )

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        yield engine

    finally:
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.drop_all)
        finally:
            await engine.dispose()


@pytest_asyncio.fixture
async def db_connection(
    test_engine: AsyncEngine,
) -> AsyncIterator[AsyncConnection]:
    """Wrap all test DB operations in a transaction that can be rolled back."""

    async with test_engine.connect() as connection:
        transaction = await connection.begin()

        try:
            yield connection
        finally:
            if transaction.is_active:
                await transaction.rollback()


@pytest_asyncio.fixture
async def client(
    db_connection: AsyncConnection,
    api_key: str,
) -> AsyncIterator[AsyncClient]:
    """Provide an HTTP client connected to the test application."""

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(
            bind=db_connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as async_client:
            yield async_client
    finally:
        app.dependency_overrides.pop(get_session, None)
