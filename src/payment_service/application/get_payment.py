from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from payment_service.domain.errors import PaymentNotFound
from payment_service.domain.payment import Payment
from payment_service.domain.ports import UnitOfWork

UnitOfWorkFactory = Callable[[], UnitOfWork]


class GetPaymentService:
    """Чтение платежа по id; отсутствие — доменная ошибка."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, payment_id: UUID) -> Payment:
        async with self._uow_factory() as uow:
            payment = await uow.payments.get(payment_id)

        if payment is None:
            raise PaymentNotFound(payment_id)

        return payment
