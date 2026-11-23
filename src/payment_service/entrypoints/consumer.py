"""Consumer платежей: FastStream → ProcessPaymentService, retry/DLQ."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
from faststream import FastStream
from faststream.middlewares import AckPolicy
from faststream.rabbit import Channel, RabbitBroker, RabbitMessage

from payment_service.application.process_payment import ProcessPaymentService
from payment_service.config import settings
from payment_service.container import make_unit_of_work, utcnow
from payment_service.domain.events import PaymentCreated
from payment_service.infrastructure.gateway import RandomPaymentGateway
from payment_service.infrastructure.messaging.topology import (
    MAX_PROCESSING_ATTEMPTS,
    PAYMENTS_DLQ_ROUTING_KEY,
    PAYMENTS_DLX_EXCHANGE,
    PAYMENTS_EXCHANGE,
    PAYMENTS_NEW_QUEUE,
    PAYMENTS_RETRY_EXCHANGE,
    RETRY_QUEUES,
    declare_topology,
)
from payment_service.infrastructure.webhook import HttpxWebhookSender

logger = logging.getLogger(__name__)

ATTEMPT_HEADER = "x-attempt"
LAST_ERROR_HEADER = "x-last-error"
MAX_ERROR_LENGTH = 1000
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
_service: ProcessPaymentService | None = None


def parse_event(payload: dict[str, Any]) -> PaymentCreated:
    """Восстанавливает доменное событие из payload сообщения."""

    return PaymentCreated(
        event_id=UUID(str(payload["event_id"])),
        payment_id=UUID(str(payload["payment_id"])),
        occurred_at=datetime.fromisoformat(str(payload["occurred_at"])),
    )


def current_attempt(headers: dict[str, Any] | None) -> int:
    """Номер текущей попытки (1-based) из заголовка ``x-attempt``."""

    raw = (headers or {}).get(ATTEMPT_HEADER, 1)

    try:
        attempt = int(raw)
    except (TypeError, ValueError):
        # Некорректный заголовок не должен включать бесконечные повторы.
        return MAX_PROCESSING_ATTEMPTS

    return min(max(attempt, 1), MAX_PROCESSING_ATTEMPTS)


async def schedule_retry_or_dead_letter(
    payload: dict[str, Any],
    *,
    attempt: int,
    error: Exception,
    rabbit_broker: RabbitBroker,
    message_id: str | None,
) -> None:
    """Публикует провалившееся сообщение в retry-очередь или DLQ.

    ``attempt`` — номер только что провалившейся попытки. Попытки 1 и 2
    уходят в retry-очереди с TTL 2 с и 4 с, попытка 3 — в ``payments.dlq``.
    """

    error_text = f"{type(error).__name__}: {error}"[:MAX_ERROR_LENGTH]
    stable_message_id = str(
        payload.get("event_id") or message_id or "unknown-event"
    )

    if attempt < MAX_PROCESSING_ATTEMPTS:
        retry_queue = RETRY_QUEUES[attempt]
        headers = {
            ATTEMPT_HEADER: attempt + 1,
            LAST_ERROR_HEADER: error_text,
        }

        logger.warning(
            "Scheduling retry %s/%s for event %s via %s: %s",
            attempt + 1,
            MAX_PROCESSING_ATTEMPTS,
            stable_message_id,
            retry_queue.name,
            error_text,
        )

        await rabbit_broker.publish(
            payload,
            exchange=PAYMENTS_RETRY_EXCHANGE,
            routing_key=retry_queue.name,
            headers=headers,
            message_id=stable_message_id,
            persist=True,
        )
        return

    logger.error(
        "Event %s failed after %s attempts; sending to DLQ: %s",
        stable_message_id,
        MAX_PROCESSING_ATTEMPTS,
        error_text,
    )

    await rabbit_broker.publish(
        payload,
        exchange=PAYMENTS_DLX_EXCHANGE,
        routing_key=PAYMENTS_DLQ_ROUTING_KEY,
        headers={
            ATTEMPT_HEADER: MAX_PROCESSING_ATTEMPTS,
            LAST_ERROR_HEADER: error_text,
        },
        message_id=stable_message_id,
        persist=True,
    )


async def process_delivery(
    payload: dict[str, Any],
    message: RabbitMessage,
    *,
    service: ProcessPaymentService,
    rabbit_broker: RabbitBroker,
) -> None:
    """Обрабатывает доставку: сервис, retry/DLQ при ошибке, затем ack."""

    attempt = current_attempt(message.headers)

    try:
        event = parse_event(payload)

        logger.info(
            "Processing payment %s, event=%s, attempt=%s",
            event.payment_id,
            event.event_id,
            attempt,
        )

        await service.execute(event)

    except asyncio.CancelledError:
        raise

    except Exception as exc:
        logger.exception(
            "Payment event failed, message_id=%s, attempt=%s",
            message.message_id,
            attempt,
        )

        # Если публикация в retry/DLQ провалится, исключение не даст
        # подтвердить оригинальное сообщение.
        await schedule_retry_or_dead_letter(
            payload,
            attempt=attempt,
            error=exc,
            rabbit_broker=rabbit_broker,
            message_id=message.message_id,
        )

    await message.ack()


@broker.subscriber(
    PAYMENTS_NEW_QUEUE,
    PAYMENTS_EXCHANGE,
    ack_policy=AckPolicy.MANUAL,
)
async def consume_payment(
    payload: dict[str, Any],
    message: RabbitMessage,
) -> None:
    """Тонкий хендлер: обработка делегируется в ``process_delivery``."""

    if _service is None:
        raise RuntimeError("ProcessPaymentService is not initialized")

    await process_delivery(
        payload,
        message,
        service=_service,
        rabbit_broker=broker,
    )


@app.after_startup
async def startup() -> None:
    """Объявляет топологию и собирает зависимости consumer'а."""

    global _http_client, _service

    await declare_topology(broker)

    _http_client = httpx.AsyncClient(
        timeout=WEBHOOK_TIMEOUT_SECONDS,
        follow_redirects=False,
    )
    _service = ProcessPaymentService(
        uow_factory=make_unit_of_work,
        gateway=RandomPaymentGateway(),
        webhook_sender=HttpxWebhookSender(
            _http_client,
            timeout_seconds=WEBHOOK_TIMEOUT_SECONDS,
        ),
        clock=utcnow,
    )

    logger.info("Payment consumer started")


@app.on_shutdown
async def shutdown() -> None:
    """Освобождает общий HTTP-клиент."""

    global _http_client, _service

    if _http_client is not None:
        await _http_client.aclose()

    _http_client = None
    _service = None

    logger.info("Payment consumer stopped")
