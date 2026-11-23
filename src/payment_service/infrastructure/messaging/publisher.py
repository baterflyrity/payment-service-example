from __future__ import annotations

from faststream.rabbit import RabbitBroker

from payment_service.domain.events import PaymentCreated
from payment_service.messaging.topology import (
    PAYMENTS_EXCHANGE,
    PAYMENTS_NEW_ROUTING_KEY,
)


def event_to_payload(event: PaymentCreated) -> dict[str, str]:
    return {
        "event_id": str(event.event_id),
        "payment_id": str(event.payment_id),
        "occurred_at": event.occurred_at.isoformat(),
    }


class FastStreamEventPublisher:
    """Публикация доменных событий в exchange ``payments``.

    ``broker.publish`` ждёт publisher confirm от RabbitMQ (aiormq включает
    publisher confirms по умолчанию), поэтому успешный возврат означает, что
    брокер принял сообщение.
    """

    def __init__(self, broker: RabbitBroker) -> None:
        self._broker = broker

    async def publish(self, event: PaymentCreated) -> None:
        await self._broker.publish(
            event_to_payload(event),
            exchange=PAYMENTS_EXCHANGE,
            routing_key=PAYMENTS_NEW_ROUTING_KEY,
            message_id=str(event.event_id),
            persist=True,
            mandatory=True,
        )
