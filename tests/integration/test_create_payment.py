import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from payment_service.api.main import app
from payment_service.application.commands import CreatePaymentCommand
from payment_service.application.create_payment import CreatePaymentService
from payment_service.container import get_unit_of_work_factory
from payment_service.domain.payment import Currency
from payment_service.infrastructure.db.orm import OutboxORM, PaymentORM
from payment_service.infrastructure.db.uow import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.integration

PAYMENTS_URL = "/api/v1/payments"


@pytest_asyncio.fixture
async def real_client(
    test_engine: AsyncEngine,
    api_key: str,
) -> AsyncIterator[AsyncClient]:
    """HTTP client whose UoW uses real connections, so requests really race."""

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    def make_uow() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    app.dependency_overrides[get_unit_of_work_factory] = lambda: make_uow

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as async_client:
            yield async_client
    finally:
        app.dependency_overrides.pop(get_unit_of_work_factory, None)


def make_payload() -> dict[str, object]:
    return {
        "amount": "125.50",
        "currency": "RUB",
        "description": "Race payment",
        "metadata": {"order_id": "order-race"},
        "webhook_url": "https://example.com/webhooks/payments",
    }


@pytest.mark.asyncio
class CommitFailingUnitOfWork(SqlAlchemyUnitOfWork):
    """UoW, падающий на commit после записи платежа и outbox-события."""

    async def commit(self) -> None:
        raise RuntimeError("commit failed after payment and outbox were written")


async def test_commit_failure_rolls_back_payment_and_outbox(
    test_engine: AsyncEngine,
) -> None:
    """Ошибка после ``outbox.add`` до commit не оставляет ни платежа, ни события."""

    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    service = CreatePaymentService(
        uow_factory=lambda: CommitFailingUnitOfWork(session_factory),
        clock=lambda: datetime(2026, 11, 23, 12, 0, tzinfo=UTC),
    )
    command = CreatePaymentCommand(
        amount=Decimal("10.00"),
        currency=Currency.RUB,
        description="Atomicity test",
        webhook_url="https://example.com/webhooks/payments",
        idempotency_key="atomicity-failure",
        metadata={"order_id": "order-atomic"},
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        await service.execute(command)

    async with AsyncSession(test_engine) as session:
        payment_count = await session.scalar(
            select(func.count()).select_from(PaymentORM),
        )
        outbox_count = await session.scalar(
            select(func.count()).select_from(OutboxORM),
        )

    assert payment_count == 0
    assert outbox_count == 0


async def test_parallel_posts_with_same_key_create_one_payment_and_event(
    real_client: AsyncClient,
    api_key: str,
    test_engine: AsyncEngine,
) -> None:
    headers = {
        "X-API-Key": api_key,
        "Idempotency-Key": "parallel-same-key",
    }

    responses = await asyncio.gather(
        *(
            real_client.post(PAYMENTS_URL, headers=headers, json=make_payload())
            for _ in range(10)
        ),
    )

    assert [response.status_code for response in responses] == [202] * 10
    assert len({response.json()["payment_id"] for response in responses}) == 1

    async with AsyncSession(test_engine) as session:
        payment_count = await session.scalar(
            select(func.count()).select_from(PaymentORM),
        )
        outbox_count = await session.scalar(
            select(func.count()).select_from(OutboxORM),
        )

    assert payment_count == 1
    assert outbox_count == 1
