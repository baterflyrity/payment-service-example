from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import pytest

from payment_service.entrypoints.consumer import process_delivery
from payment_service.infrastructure.messaging.topology import (
    MAX_PROCESSING_ATTEMPTS,
    PAYMENTS_DLQ,
    PAYMENTS_DLQ_ROUTING_KEY,
    PAYMENTS_DLX_EXCHANGE,
    PAYMENTS_RETRY_2S_QUEUE,
    PAYMENTS_RETRY_4S_QUEUE,
    PAYMENTS_RETRY_EXCHANGE,
)


class FakeMessage:
    def __init__(self, headers: Mapping[str, Any] | None = None) -> None:
        self.headers = dict(headers or {})
        self.message_id = "message-id"
        self.acked = 0

    async def ack(self) -> None:
        self.acked += 1


class FakeBroker:
    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    async def publish(self, payload: dict[str, Any], **kwargs: Any) -> None:
        self.published.append({"payload": payload, **kwargs})


class OkService:
    async def execute(self, event: object) -> None:
        del event


class FailingService:
    def __init__(self, error: Exception) -> None:
        self._error = error
        self.calls = 0

    async def execute(self, event: object) -> None:
        del event
        self.calls += 1
        raise self._error


def make_payload() -> dict[str, str]:
    return {
        "event_id": str(uuid4()),
        "payment_id": str(uuid4()),
        "occurred_at": "2026-11-23T12:00:00+00:00",
    }


@pytest.mark.asyncio
async def test_successful_delivery_acks_without_publishing() -> None:
    broker = FakeBroker()
    message = FakeMessage()

    await process_delivery(
        make_payload(),
        message,
        service=OkService(),  # type: ignore[arg-type]
        rabbit_broker=broker,  # type: ignore[arg-type]
    )

    assert broker.published == []
    assert message.acked == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("header_attempt", "expected_queue", "expected_attempt", "expected_ttl_ms"),
    [
        (None, PAYMENTS_RETRY_2S_QUEUE, 2, 2_000),
        ("1", PAYMENTS_RETRY_2S_QUEUE, 2, 2_000),
        ("2", PAYMENTS_RETRY_4S_QUEUE, 3, 4_000),
    ],
)
async def test_first_and_second_failures_go_to_retry_queues(
    header_attempt: str | None,
    expected_queue,
    expected_attempt: int,
    expected_ttl_ms: int,
) -> None:
    broker = FakeBroker()
    message = FakeMessage(
        {"x-attempt": header_attempt} if header_attempt is not None else None,
    )
    payload = make_payload()

    await process_delivery(
        payload,
        message,
        service=FailingService(RuntimeError("webhook is down")),  # type: ignore[arg-type]
        rabbit_broker=broker,  # type: ignore[arg-type]
    )

    assert message.acked == 1
    assert len(broker.published) == 1

    call = broker.published[0]
    assert call["payload"] == payload
    assert call["exchange"] == PAYMENTS_RETRY_EXCHANGE
    assert call["routing_key"] == expected_queue.name
    assert call["headers"]["x-attempt"] == expected_attempt
    assert "webhook is down" in call["headers"]["x-last-error"]
    assert call["persist"] is True

    assert expected_queue.arguments["x-message-ttl"] == expected_ttl_ms
    assert expected_queue.arguments["x-dead-letter-exchange"] == "payments"
    assert expected_queue.arguments["x-dead-letter-routing-key"] == "payments.new"


@pytest.mark.asyncio
async def test_third_failure_goes_to_dlq() -> None:
    broker = FakeBroker()
    message = FakeMessage({"x-attempt": str(MAX_PROCESSING_ATTEMPTS)})
    payload = make_payload()

    await process_delivery(
        payload,
        message,
        service=FailingService(RuntimeError("webhook is down")),  # type: ignore[arg-type]
        rabbit_broker=broker,  # type: ignore[arg-type]
    )

    assert message.acked == 1
    assert len(broker.published) == 1

    call = broker.published[0]
    assert call["exchange"] == PAYMENTS_DLX_EXCHANGE
    assert call["routing_key"] == PAYMENTS_DLQ_ROUTING_KEY
    assert call["routing_key"] == PAYMENTS_DLQ.name
    assert call["headers"]["x-attempt"] == MAX_PROCESSING_ATTEMPTS
    assert "webhook is down" in call["headers"]["x-last-error"]


@pytest.mark.asyncio
async def test_publish_failure_does_not_ack() -> None:
    class BrokenBroker(FakeBroker):
        async def publish(self, payload: dict[str, Any], **kwargs: Any) -> None:
            del payload, kwargs
            raise RuntimeError("rabbit is down")

    message = FakeMessage()

    with pytest.raises(RuntimeError, match="rabbit is down"):
        await process_delivery(
            make_payload(),
            message,
            service=FailingService(RuntimeError("webhook is down")),  # type: ignore[arg-type]
            rabbit_broker=BrokenBroker(),  # type: ignore[arg-type]
        )

    assert message.acked == 0
