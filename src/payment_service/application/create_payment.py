from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from payment_service.application.commands import CreatePaymentCommand
from payment_service.application.idempotency import calculate_request_hash
from payment_service.domain.errors import DuplicateIdempotencyKey
from payment_service.domain.payment import Payment
from payment_service.domain.ports import UnitOfWork

UnitOfWorkFactory = Callable[[], UnitOfWork]
Clock = Callable[[], datetime]


class CreatePaymentService:
    """Создание платежа с идемпотентностью и записью outbox-события.

    Платёж и событие пишутся в одной единице работы. При гонке одинаковых
    Idempotency-Key уникальное ограничение БД даёт ``DuplicateIdempotencyKey``;
    сервис перечитывает ключ в новом UoW и повторяет сверку.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(
        self,
        command: CreatePaymentCommand,
    ) -> tuple[Payment, bool]:
        request_hash = calculate_request_hash(command)

        existing = await self._find_by_key(command.idempotency_key)
        if existing is not None:
            existing.ensure_same_request(request_hash)
            return existing, False

        try:
            payment = await self._create(command, request_hash)
        except DuplicateIdempotencyKey:
            existing = await self._find_by_key(command.idempotency_key)
            if existing is None:
                raise
            existing.ensure_same_request(request_hash)
            return existing, False

        return payment, True

    async def _find_by_key(self, idempotency_key: str) -> Payment | None:
        async with self._uow_factory() as uow:
            return await uow.payments.get_by_idempotency_key(idempotency_key)

    async def _create(
        self,
        command: CreatePaymentCommand,
        request_hash: str,
    ) -> Payment:
        payment = Payment.create(
            amount=command.amount,
            currency=command.currency,
            description=command.description,
            metadata=command.metadata,
            idempotency_key=command.idempotency_key,
            request_hash=request_hash,
            webhook_url=command.webhook_url,
            now=self._clock(),
        )
        events = payment.pull_events()

        async with self._uow_factory() as uow:
            await uow.payments.add(payment)

            for event in events:
                await uow.outbox.add(event)

            await uow.commit()

        return payment
