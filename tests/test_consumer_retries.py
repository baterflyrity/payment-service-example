from unittest.mock import AsyncMock, Mock

import pytest
from faststream.rabbit import RabbitBroker

from payment_service.messaging.topology import (
    MAX_PROCESSING_ATTEMPTS,
    PAYMENTS_DLQ,
    PAYMENTS_RETRY_2S_QUEUE,
    PAYMENTS_RETRY_4S_QUEUE,
)
from payment_service.workers.consumer import retry_or_dead_letter


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("retry_count", "expected_queue", "expected_header"),
    [
        (0, PAYMENTS_RETRY_2S_QUEUE, 1),
        (1, PAYMENTS_RETRY_4S_QUEUE, 2),
        (2, PAYMENTS_DLQ, MAX_PROCESSING_ATTEMPTS),
    ],
)
async def test_failed_message_is_routed_correctly(
    retry_count: int,
    expected_queue,
    expected_header: int,
) -> None:
    broker_mock = Mock(spec=RabbitBroker)
    broker_mock.publish = AsyncMock()

    payload = {
        "event_id": "d3923897-a64a-4f15-b1a5-c12e7e4a9232",
        "payment_id": "2b6a3838-b85b-4592-b779-904d02db77c3",
    }

    await retry_or_dead_letter(
        payload,
        retry_count=retry_count,
        error=RuntimeError("simulated failure"),
        message_id="d3923897-a64a-4f15-b1a5-c12e7e4a9232",
        rabbit_broker=broker_mock,
    )

    broker_mock.publish.assert_awaited_once()

    call = broker_mock.publish.await_args
    assert call is not None

    assert call.args[0] == payload
    assert call.kwargs["queue"] == expected_queue
    assert call.kwargs["headers"]["x-retry-count"] == expected_header
    assert "simulated failure" in call.kwargs["headers"]["x-last-error"]
    assert call.kwargs["persist"] is True
    assert call.kwargs["mandatory"] is True
