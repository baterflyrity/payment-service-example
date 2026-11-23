from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from payment_service.domain.events import OutboxMessage, PaymentCreated
from payment_service.domain.ports import EventPublisher, UnitOfWork

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 2000


def message_to_event(message: OutboxMessage) -> PaymentCreated:
    """Восстанавливает доменное событие из payload записи outbox."""

    payload = message.payload

    return PaymentCreated(
        event_id=message.event_id,
        payment_id=UUID(str(payload["payment_id"])),
        occurred_at=datetime.fromisoformat(str(payload["occurred_at"])),
    )


class RelayOutboxService:
    """Публикует неопубликованные события outbox в брокер.

    Гарантия at-least-once: запись помечается опубликованной только после
    подтверждения брокером и в той же транзакции; при ошибке публикации
    увеличивается ``attempts`` и заполняется ``last_error``, а событие
    остаётся в outbox для следующего прохода.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        publisher: EventPublisher,
        batch_size: int,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")

        self._uow_factory = uow_factory
        self._publisher = publisher
        self._batch_size = batch_size

    async def run_once(self) -> int:
        """Публикует очередную партию событий; возвращает число успешных."""

        published_count = 0

        async with self._uow_factory() as uow:
            messages = await uow.outbox.lock_unpublished(self._batch_size)
            published_ids: list[UUID] = []

            for message in messages:
                try:
                    await self._publisher.publish(message_to_event(message))
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH]

                    await uow.outbox.mark_failed(message.id, error)

                    logger.exception(
                        "Failed to publish outbox event %s; it will be retried",
                        message.id,
                    )
                    continue

                published_ids.append(message.id)
                published_count += 1

                logger.info(
                    "Published outbox event %s, type=%s",
                    message.id,
                    message.event_type,
                )

            await uow.outbox.mark_published(published_ids)
            await uow.commit()

        return published_count
