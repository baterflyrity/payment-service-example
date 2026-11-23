from __future__ import annotations

from uuid import UUID

from payment_service.domain.events import OutboxMessage
from payment_service.domain.payment import Currency, Payment, PaymentStatus
from payment_service.infrastructure.db.orm import OutboxORM, PaymentORM


def payment_to_orm(payment: Payment) -> PaymentORM:
    return PaymentORM(
        id=payment.id,
        amount=payment.amount,
        currency=payment.currency.value,
        description=payment.description,
        metadata_json=dict(payment.metadata),
        status=payment.status.value,
        idempotency_key=payment.idempotency_key,
        request_hash=payment.request_hash,
        webhook_url=payment.webhook_url,
        created_at=payment.created_at,
        processed_at=payment.processed_at,
    )


def apply_payment_to_orm(orm: PaymentORM, payment: Payment) -> None:
    """Переносит изменяемые поля доменной сущности в существующую ORM-запись."""

    orm.amount = payment.amount
    orm.currency = payment.currency.value
    orm.description = payment.description
    orm.metadata_json = dict(payment.metadata)
    orm.status = payment.status.value
    orm.idempotency_key = payment.idempotency_key
    orm.request_hash = payment.request_hash
    orm.webhook_url = payment.webhook_url
    orm.created_at = payment.created_at
    orm.processed_at = payment.processed_at


def payment_to_domain(orm: PaymentORM) -> Payment:
    return Payment(
        id=orm.id,
        amount=orm.amount,
        currency=Currency(orm.currency),
        description=orm.description,
        metadata=dict(orm.metadata_json),
        status=PaymentStatus(orm.status),
        idempotency_key=orm.idempotency_key,
        request_hash=orm.request_hash,
        webhook_url=orm.webhook_url,
        created_at=orm.created_at,
        processed_at=orm.processed_at,
    )


def outbox_to_message(orm: OutboxORM) -> OutboxMessage:
    raw_event_id = orm.payload.get("event_id")
    event_id: UUID = UUID(str(raw_event_id)) if raw_event_id else orm.id

    return OutboxMessage(
        id=orm.id,
        event_id=event_id,
        event_type=orm.event_type,
        payload=dict(orm.payload),
        attempts=orm.attempts,
    )
