from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from payment_service.domain import (
    DuplicateIdempotencyKey,
    Payment,
    PaymentCreated,
    PaymentStatus,
)
from payment_service.infrastructure.db.uow import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def session_factory(
    test_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async with test_engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE outbox, payments"))

    yield async_sessionmaker(test_engine, expire_on_commit=False)


def make_payment(
    *,
    idempotency_key: str = "idem-key-1",
    request_hash: str = "a" * 64,
) -> Payment:
    return Payment.create(
        amount=Decimal("10.50"),
        currency="USD",
        description="Integration test payment",
        metadata={"order_id": "42"},
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        webhook_url="https://example.test/webhook",
        now=datetime(2026, 11, 23, 12, 0, tzinfo=UTC),
    )


def make_event() -> PaymentCreated:
    return PaymentCreated(
        event_id=uuid4(),
        payment_id=uuid4(),
        occurred_at=datetime(2026, 11, 23, 12, 0, tzinfo=UTC),
    )


async def test_add_and_read_payment(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    payment = make_payment()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.payments.add(payment)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        loaded = await uow.payments.get(payment.id)
        by_key = await uow.payments.get_by_idempotency_key(payment.idempotency_key)
        locked = await uow.payments.get_for_update(payment.id)

    assert loaded == payment
    assert by_key == payment
    assert locked == payment
    assert loaded is not None
    assert loaded.status is PaymentStatus.PENDING


async def test_add_updates_existing_payment(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    payment = make_payment()
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.payments.add(payment)
        await uow.commit()

    payment.mark_succeeded(datetime(2026, 11, 23, 12, 5, tzinfo=UTC))

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.payments.add(payment)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        loaded = await uow.payments.get(payment.id)

    assert loaded is not None
    assert loaded.status is PaymentStatus.SUCCEEDED
    assert loaded.processed_at == datetime(2026, 11, 23, 12, 5, tzinfo=UTC)


async def test_duplicate_idempotency_key_raises_domain_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.payments.add(make_payment())
        await uow.commit()

    duplicate = make_payment()

    with pytest.raises(DuplicateIdempotencyKey):
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await uow.payments.add(duplicate)


async def test_uow_rolls_back_without_commit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    payment = make_payment()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.payments.add(payment)
        assert await uow.payments.get(payment.id) is not None

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        assert await uow.payments.get(payment.id) is None


async def test_uow_rolls_back_on_exception(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    payment = make_payment()

    with pytest.raises(RuntimeError):
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await uow.payments.add(payment)
            raise RuntimeError("boom")

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        assert await uow.payments.get(payment.id) is None


async def test_lock_unpublished_skips_rows_locked_by_another_uow(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.outbox.add(make_event())
        await uow.outbox.add(make_event())
        await uow.commit()

    async with (
        SqlAlchemyUnitOfWork(session_factory) as first,
        SqlAlchemyUnitOfWork(session_factory) as second,
    ):
        locked_by_first = await first.outbox.lock_unpublished(10)
        locked_by_second = await second.outbox.lock_unpublished(10)

        assert len(locked_by_first) == 2
        assert locked_by_second == []


async def test_outbox_mark_published_and_mark_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.outbox.add(make_event())
        await uow.outbox.add(make_event())
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        messages = await uow.outbox.lock_unpublished(10)
        assert len(messages) == 2

        await uow.outbox.mark_failed(messages[0].id, "publish failed")
        await uow.outbox.mark_published([messages[1].id])
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        remaining = await uow.outbox.lock_unpublished(10)

    assert len(remaining) == 1
    assert remaining[0].id == messages[0].id
    assert remaining[0].attempts == 1
    assert isinstance(remaining[0].id, UUID)
