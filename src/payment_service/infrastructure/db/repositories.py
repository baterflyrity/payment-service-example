from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.domain.errors import DuplicateIdempotencyKey
from payment_service.domain.events import OutboxMessage, PaymentCreated
from payment_service.domain.payment import Payment
from payment_service.infrastructure.db.mappers import (
    apply_payment_to_orm,
    outbox_to_message,
    payment_to_domain,
    payment_to_orm,
)
from payment_service.infrastructure.db.orm import OutboxORM, PaymentORM


def _is_duplicate_idempotency_key(error: IntegrityError) -> bool:
    """Уникальность idempotency_key может называться по-разному.

    В миграции ограничение названо ``uq_payments_idempotency_key``, а
    ``create_all`` в тестах генерирует ``payments_idempotency_key_key``.
    """

    constraint = getattr(error.orig, "constraint_name", None)
    if constraint is not None:
        return "idempotency_key" in str(constraint)

    return "idempotency_key" in str(error.orig)


class SqlAlchemyPaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, payment: Payment) -> None:
        orm = await self._session.get(PaymentORM, payment.id)

        if orm is None:
            self._session.add(payment_to_orm(payment))
        else:
            apply_payment_to_orm(orm, payment)

        try:
            await self._session.flush()
        except IntegrityError as exc:
            if _is_duplicate_idempotency_key(exc):
                raise DuplicateIdempotencyKey(payment.idempotency_key) from exc
            raise

    async def get(self, payment_id: UUID) -> Payment | None:
        orm = await self._session.get(PaymentORM, payment_id)
        return payment_to_domain(orm) if orm is not None else None

    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        orm = await self._session.scalar(
            select(PaymentORM).where(
                PaymentORM.idempotency_key == idempotency_key,
            ),
        )
        return payment_to_domain(orm) if orm is not None else None

    async def get_for_update(self, payment_id: UUID) -> Payment | None:
        orm = await self._session.scalar(
            select(PaymentORM)
            .where(PaymentORM.id == payment_id)
            .with_for_update(),
        )
        return payment_to_domain(orm) if orm is not None else None


class SqlAlchemyOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: PaymentCreated) -> None:
        self._session.add(
            OutboxORM(
                event_type=event.event_type,
                aggregate_id=event.payment_id,
                payload={
                    "event_id": str(event.event_id),
                    "payment_id": str(event.payment_id),
                    "occurred_at": event.occurred_at.isoformat(),
                },
            ),
        )
        await self._session.flush()

    async def lock_unpublished(self, limit: int) -> Sequence[OutboxMessage]:
        result = await self._session.scalars(
            select(OutboxORM)
            .where(OutboxORM.published_at.is_(None))
            .order_by(OutboxORM.created_at, OutboxORM.id)
            .limit(limit)
            .with_for_update(skip_locked=True),
        )
        return [outbox_to_message(orm) for orm in result.all()]

    async def mark_published(self, ids: Sequence[UUID]) -> None:
        if not ids:
            return

        await self._session.execute(
            update(OutboxORM)
            .where(OutboxORM.id.in_(ids))
            .values(published_at=func.now()),
        )

    async def mark_failed(self, id: UUID, error: str) -> None:
        await self._session.execute(
            update(OutboxORM)
            .where(OutboxORM.id == id)
            .values(
                attempts=OutboxORM.attempts + 1,
                last_error=error,
            ),
        )
