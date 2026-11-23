"""Интеграционный тест retry/DLQ на реальном RabbitMQ (marker ``rabbit``)."""

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from faststream.middlewares import AckPolicy
from faststream.rabbit import RabbitBroker, RabbitMessage

from payment_service.config import settings
from payment_service.entrypoints.consumer import process_delivery
from payment_service.infrastructure.messaging.topology import (
    PAYMENTS_DLQ,
    PAYMENTS_EXCHANGE,
    PAYMENTS_NEW_QUEUE,
    PAYMENTS_NEW_ROUTING_KEY,
    declare_topology,
)

pytestmark = [pytest.mark.integration, pytest.mark.rabbit]

DLQ_TIMEOUT_SECONDS = 20.0
# Первая попытка + TTL retry.1 (2 с) + TTL retry.2 (4 с).
MIN_PROCESSING_SECONDS = 5.0


class AlwaysFailingWebhookService:
    async def execute(self, event: object) -> None:
        del event
        raise RuntimeError("webhook endpoint is permanently down")


@pytest_asyncio.fixture
async def rabbit_broker() -> AsyncIterator[RabbitBroker]:
    broker = RabbitBroker(settings.rabbitmq_url)

    try:
        await asyncio.wait_for(broker.connect(), timeout=5.0)
    except Exception:
        await broker.stop()
        pytest.skip("RabbitMQ is not available")

    try:
        yield broker
    finally:
        await broker.stop()


async def test_permanently_failing_webhook_ends_in_dlq(
    rabbit_broker: RabbitBroker,
) -> None:
    broker = rabbit_broker
    dead_letters: list[dict[str, Any]] = []
    event_id = uuid4()
    payment_id = uuid4()

    payload = {
        "event_id": str(event_id),
        "payment_id": str(payment_id),
        "occurred_at": "2026-11-23T12:00:00+00:00",
    }

    @broker.subscriber(PAYMENTS_DLQ, ack_policy=AckPolicy.MANUAL)
    async def on_dead_letter(
        message_payload: dict[str, Any],
        message: RabbitMessage,
    ) -> None:
        dead_letters.append(message_payload)
        await message.ack()

    @broker.subscriber(
        PAYMENTS_NEW_QUEUE,
        PAYMENTS_EXCHANGE,
        ack_policy=AckPolicy.MANUAL,
    )
    async def on_payment_created(
        message_payload: dict[str, Any],
        message: RabbitMessage,
    ) -> None:
        await process_delivery(
            message_payload,
            message,
            service=AlwaysFailingWebhookService(),  # type: ignore[arg-type]
            rabbit_broker=broker,
        )

    await declare_topology(broker)
    await broker.start()

    started_at = time.monotonic()

    try:
        await broker.publish(
            payload,
            exchange=PAYMENTS_EXCHANGE,
            routing_key=PAYMENTS_NEW_ROUTING_KEY,
            persist=True,
        )

        deadline = started_at + DLQ_TIMEOUT_SECONDS

        while not dead_letters:
            if time.monotonic() > deadline:
                pytest.fail(
                    "Message did not reach payments.dlq within "
                    f"{DLQ_TIMEOUT_SECONDS:.0f} s"
                )
            await asyncio.sleep(0.1)
    finally:
        await broker.stop()

    elapsed = time.monotonic() - started_at

    assert dead_letters[0]["event_id"] == str(event_id)
    assert elapsed >= MIN_PROCESSING_SECONDS
