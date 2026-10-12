from typing import cast
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from faststream.rabbit import RabbitBroker
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payment_service.models import Outbox
from payment_service.workers.outbox_publisher import publish_outbox_batch


async def add_outbox_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> Outbox:
    async with session_factory() as session:
        async with session.begin():
            event = Outbox(
                event_type="payments.new",
                aggregate_id=uuid4(),
                payload={
                    "event_id": str(uuid4()),
                    "payment_id": str(uuid4()),
                },
            )
            session.add(event)
            await session.flush()

        return event


@pytest.mark.asyncio
async def test_publisher_marks_event_as_published(
    test_engine,
) -> None:
    session_factory = async_sessionmaker(
        test_engine,
        expire_on_commit=False,
    )
    event = await add_outbox_event(session_factory)

    broker_mock = Mock(spec=RabbitBroker)
    broker_mock.publish = AsyncMock()

    published_count = await publish_outbox_batch(
        session_factory,
        cast(RabbitBroker, broker_mock),
    )

    assert published_count == 1
    broker_mock.publish.assert_awaited_once()

    call = broker_mock.publish.await_args
    assert call is not None
    assert call.args[0] == event.payload
    assert call.kwargs["message_id"] == str(event.id)
    assert call.kwargs["persist"] is True
    assert call.kwargs["mandatory"] is True

    async with session_factory() as session:
        saved_event = await session.get(Outbox, event.id)

        assert saved_event is not None
        assert saved_event.published_at is not None
        assert saved_event.attempts == 1
        assert saved_event.last_error is None


@pytest.mark.asyncio
async def test_publisher_keeps_event_pending_on_failure(
    test_engine,
) -> None:
    session_factory = async_sessionmaker(
        test_engine,
        expire_on_commit=False,
    )
    event = await add_outbox_event(session_factory)

    broker_mock = Mock(spec=RabbitBroker)
    broker_mock.publish = AsyncMock(
        side_effect=RuntimeError("RabbitMQ unavailable"),
    )

    published_count = await publish_outbox_batch(
        session_factory,
        cast(RabbitBroker, broker_mock),
    )

    assert published_count == 0
    broker_mock.publish.assert_awaited_once()

    async with session_factory() as session:
        saved_event = await session.get(Outbox, event.id)

        assert saved_event is not None
        assert saved_event.published_at is None
        assert saved_event.attempts == 1
        assert saved_event.last_error is not None
        assert "RabbitMQ unavailable" in saved_event.last_error


@pytest.mark.asyncio
async def test_publisher_respects_batch_size(
    test_engine,
) -> None:
    session_factory = async_sessionmaker(
        test_engine,
        expire_on_commit=False,
    )

    await add_outbox_event(session_factory)
    await add_outbox_event(session_factory)

    broker_mock = Mock(spec=RabbitBroker)
    broker_mock.publish = AsyncMock()

    published_count = await publish_outbox_batch(
        session_factory,
        cast(RabbitBroker, broker_mock),
        batch_size=1,
    )

    assert published_count == 1
    assert broker_mock.publish.await_count == 1

    async with session_factory() as session:
        pending_count = await session.scalar(
            select(func.count()).select_from(Outbox).where(Outbox.published_at.is_(None)),
        )

        assert pending_count == 1
