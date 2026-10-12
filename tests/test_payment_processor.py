from decimal import Decimal
from typing import Literal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payment_service.models import Payment
from payment_service.schemas.events import PaymentCreatedEvent
from payment_service.services.payment_processor import process_payment_event


@pytest.mark.asyncio
async def test_webhook_retry_does_not_process_payment_twice(
    test_engine,
) -> None:
    session_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    payment_id = uuid4()
    event_id = uuid4()
    gateway_calls = 0
    webhook_calls = 0

    async def successful_gateway() -> Literal["succeeded"]:
        nonlocal gateway_calls
        gateway_calls += 1
        return "succeeded"

    def webhook_handler(request: httpx.Request) -> httpx.Response:
        nonlocal webhook_calls
        webhook_calls += 1

        if webhook_calls == 1:
            return httpx.Response(500, request=request)

        return httpx.Response(204, request=request)

    async with session_factory() as session:
        async with session.begin():
            session.add(
                Payment(
                    id=payment_id,
                    amount=Decimal("125.50"),
                    currency="RUB",
                    description="Processor test",
                    metadata_json={},
                    status="pending",
                    idempotency_key=f"processor-test-{payment_id}",
                    request_hash="a" * 64,
                    webhook_url="https://example.com/webhook",
                ),
            )

    event = PaymentCreatedEvent(
        event_id=event_id,
        payment_id=payment_id,
    )

    transport = httpx.MockTransport(webhook_handler)

    async with httpx.AsyncClient(transport=transport) as http_client:
        with pytest.raises(httpx.HTTPStatusError):
            await process_payment_event(
                event,
                http_client=http_client,
                session_factory=session_factory,
                gateway=successful_gateway,
            )

        # The retry repeats the webhook but not payment processing.
        await process_payment_event(
            event,
            http_client=http_client,
            session_factory=session_factory,
            gateway=successful_gateway,
        )

    assert gateway_calls == 1
    assert webhook_calls == 2

    async with session_factory() as session:
        payment = await session.scalar(
            select(Payment).where(Payment.id == payment_id),
        )

        assert payment is not None
        assert payment.status == "succeeded"
        assert payment.processed_at is not None
