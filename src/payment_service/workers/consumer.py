import asyncio
import logging
from typing import Any

import httpx
from faststream import AckPolicy, FastStream
from faststream.rabbit import Channel, RabbitBroker, RabbitMessage

from payment_service.config import settings
from payment_service.db import SessionFactory
from payment_service.messaging.topology import (
    MAX_PROCESSING_ATTEMPTS,
    PAYMENTS_DLQ,
    PAYMENTS_NEW_QUEUE,
    PAYMENTS_RETRY_2S_QUEUE,
    PAYMENTS_RETRY_4S_QUEUE,
    RETRY_QUEUES,
)
from payment_service.schemas.events import PaymentCreatedEvent
from payment_service.services.payment_processor import process_payment_event

logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT_SECONDS = 10.0

broker = RabbitBroker(
    settings.rabbitmq_url,
    default_channel=Channel(
        prefetch_count=1,
        publisher_confirms=True,
        on_return_raises=True,
    ),
)

app = FastStream(broker)

_http_client: httpx.AsyncClient | None = None


@app.after_startup
async def startup() -> None:
    """Initialize resources and declare retry/DLQ queues."""

    global _http_client

    await broker.declare_queue(PAYMENTS_RETRY_2S_QUEUE)
    await broker.declare_queue(PAYMENTS_RETRY_4S_QUEUE)
    await broker.declare_queue(PAYMENTS_DLQ)

    _http_client = httpx.AsyncClient(
        timeout=WEBHOOK_TIMEOUT_SECONDS,
        follow_redirects=False,
    )

    logger.info("Payment consumer started")


@app.on_shutdown
async def shutdown() -> None:
    """Release the shared HTTP client."""

    global _http_client

    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None

    logger.info("Payment consumer stopped")


async def retry_or_dead_letter(
    payload: dict[str, Any],
    *,
    retry_count: int,
    error: Exception,
    message_id: str | None,
    rabbit_broker: RabbitBroker = broker,
) -> None:
    """Publish a failed message to a retry queue or the final DLQ.

    retry_count is the number of retries already performed:
    0 means the initial delivery, 1 the first retry, and 2 the second retry.
    """

    if retry_count < 0:
        retry_count = 0

    error_text = f"{type(error).__name__}: {error}"[:1000]
    next_retry = retry_count + 1

    event_id = payload.get("event_id")
    stable_message_id = str(event_id or message_id or "unknown-event")

    if next_retry < MAX_PROCESSING_ATTEMPTS:
        target_queue = RETRY_QUEUES[next_retry]

        headers = {
            "x-retry-count": next_retry,
            "x-last-error": error_text,
        }

        logger.warning(
            "Scheduling retry %s/%s for event %s via %s: %s",
            next_retry,
            MAX_PROCESSING_ATTEMPTS - 1,
            stable_message_id,
            target_queue.name,
            error_text,
        )
    else:
        target_queue = PAYMENTS_DLQ

        headers = {
            "x-retry-count": MAX_PROCESSING_ATTEMPTS,
            "x-last-error": error_text,
        }

        logger.error(
            "Event %s failed after %s attempts; sending to DLQ: %s",
            stable_message_id,
            MAX_PROCESSING_ATTEMPTS,
            error_text,
        )

    # Do not swallow publish errors. If publishing to retry/DLQ fails,
    # the exception must reach FastStream so the original delivery is not
    # acknowledged as successfully handled.
    await rabbit_broker.publish(
        payload,
        queue=target_queue,
        headers=headers,
        message_id=stable_message_id,
        mandatory=True,
        persist=True,
    )


@broker.subscriber(
    PAYMENTS_NEW_QUEUE,
    ack_policy=AckPolicy.NACK_ON_ERROR,
)
async def consume_payment(
    payload: dict[str, Any],
    message: RabbitMessage,
) -> None:
    """Process a payment event and arrange retry/DLQ on failure."""

    retry_count_raw = (message.headers or {}).get("x-retry-count", 0)

    try:
        retry_count = int(retry_count_raw)
    except TypeError, ValueError:
        # An invalid retry counter must not cause endless redelivery.
        retry_count = MAX_PROCESSING_ATTEMPTS - 1

    if retry_count >= MAX_PROCESSING_ATTEMPTS:
        retry_count = MAX_PROCESSING_ATTEMPTS - 1

    try:
        if _http_client is None:
            raise RuntimeError("Webhook HTTP client is not initialized")

        event = PaymentCreatedEvent.model_validate(payload)

        logger.info(
            "Processing payment %s, event=%s, delivery attempt=%s",
            event.payment_id,
            event.event_id,
            retry_count + 1,
        )

        await process_payment_event(
            event,
            http_client=_http_client,
            session_factory=SessionFactory,
        )

        logger.info(
            "Payment event %s processed successfully",
            event.event_id,
        )

    except asyncio.CancelledError:
        raise

    except Exception as exc:
        logger.exception(
            "Payment event failed, message_id=%s, retry_count=%s",
            message.message_id,
            retry_count,
        )

        # If retry/DLQ publication itself fails, let the exception propagate.
        await retry_or_dead_letter(
            payload,
            retry_count=retry_count,
            error=exc,
            message_id=message.message_id,
        )
