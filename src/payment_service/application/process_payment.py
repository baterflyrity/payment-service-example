"""Use case обработки события о создании платежа consumer'ом."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from payment_service.domain.errors import PaymentNotFound
from payment_service.domain.events import PaymentCreated
from payment_service.domain.payment import Payment
from payment_service.domain.ports import (
    PaymentGateway,
    UnitOfWork,
    WebhookSender,
)

UnitOfWorkFactory = Callable[[], UnitOfWork]
Clock = Callable[[], datetime]


def build_webhook_payload(
    event_id: UUID,
    payment: Payment,
) -> dict[str, Any]:
    """Плоский payload webhook-уведомления о результате платежа."""

    return {
        "event_id": str(event_id),
        "payment_id": str(payment.id),
        "status": payment.status.value,
        "amount": format(payment.amount, ".2f"),
        "currency": payment.currency.value,
        "processed_at": (
            payment.processed_at.isoformat()
            if payment.processed_at is not None
            else None
        ),
    }


class ProcessPaymentService:
    """Обрабатывает платёж идемпотентно.

    Шлюз вызывается только для платежа в статусе ``pending`` и вне
    транзакции с блокировкой строки. Результат сохраняется до отправки
    webhook; если платёж уже в финальном статусе (повторное событие или
    конкурентный consumer), шлюз не вызывается, отправляется только webhook.

    Ошибка webhook пробрасывается наружу — consumer отправит сообщение
    в retry-очередь, при этом платёж не будет обработан повторно.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        gateway: PaymentGateway,
        webhook_sender: WebhookSender,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._gateway = gateway
        self._webhook_sender = webhook_sender
        self._clock = clock

    async def execute(self, event: PaymentCreated) -> None:
        payment = await self._load_for_update(event.payment_id)

        if not payment.is_final:
            succeeded = await self._gateway.process(
                payment.id,
                payment.amount,
                payment.currency,
            )
            payment = await self._store_result(event.payment_id, succeeded)

        await self._webhook_sender.send(
            payment.webhook_url,
            build_webhook_payload(event.event_id, payment),
        )

    async def _load_for_update(self, payment_id: UUID) -> Payment:
        async with self._uow_factory() as uow:
            payment = await uow.payments.get_for_update(payment_id)

        if payment is None:
            raise PaymentNotFound(payment_id)

        return payment

    async def _store_result(self, payment_id: UUID, succeeded: bool) -> Payment:
        async with self._uow_factory() as uow:
            payment = await uow.payments.get_for_update(payment_id)

            if payment is None:
                raise PaymentNotFound(payment_id)

            # Конкурентный consumer мог успеть зафиксировать результат,
            # пока мы ждали шлюз: не перезаписываем финальный статус.
            if payment.is_final:
                return payment

            now = self._clock()

            if succeeded:
                payment.mark_succeeded(now)
            else:
                payment.mark_failed(now)

            await uow.payments.add(payment)
            await uow.commit()

        return payment
