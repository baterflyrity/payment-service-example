from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Self
from uuid import UUID, uuid4

from payment_service.domain.errors import (
    IdempotencyConflict,
    InvalidStatusTransition,
)
from payment_service.domain.events import PaymentCreated

_CENT = Decimal("0.01")


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Currency(StrEnum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


@dataclass(slots=True)
class Payment:
    id: UUID
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, Any]
    status: PaymentStatus
    idempotency_key: str
    request_hash: str
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None = None
    _events: list[PaymentCreated] = field(
        default_factory=list, init=False, repr=False, compare=False
    )

    @classmethod
    def create(
        cls,
        *,
        amount: Decimal | int | str,
        currency: Currency | str,
        description: str,
        metadata: dict[str, Any] | None,
        idempotency_key: str,
        request_hash: str,
        webhook_url: str,
        now: datetime | None = None,
    ) -> Self:
        normalized_amount = _normalize_amount(amount)
        created_at = now or datetime.now(UTC)

        payment = cls(
            id=uuid4(),
            amount=normalized_amount,
            currency=Currency(currency),
            description=description,
            metadata=dict(metadata or {}),
            status=PaymentStatus.PENDING,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            webhook_url=webhook_url,
            created_at=created_at,
        )
        payment._events.append(
            PaymentCreated(
                event_id=uuid4(),
                payment_id=payment.id,
                occurred_at=created_at,
            )
        )
        return payment

    @property
    def is_final(self) -> bool:
        return self.status in (PaymentStatus.SUCCEEDED, PaymentStatus.FAILED)

    def mark_succeeded(self, now: datetime) -> None:
        self._transition_to(PaymentStatus.SUCCEEDED, now)

    def mark_failed(self, now: datetime) -> None:
        self._transition_to(PaymentStatus.FAILED, now)

    def ensure_same_request(self, request_hash: str) -> None:
        if request_hash != self.request_hash:
            raise IdempotencyConflict(self.idempotency_key)

    def pull_events(self) -> list[PaymentCreated]:
        events = list(self._events)
        self._events.clear()
        return events

    def _transition_to(self, target: PaymentStatus, now: datetime) -> None:
        if self.status is not PaymentStatus.PENDING:
            raise InvalidStatusTransition(self.status.value, target.value)
        self.status = target
        self.processed_at = now


def _normalize_amount(amount: Decimal | int | str) -> Decimal:
    try:
        normalized = Decimal(amount).quantize(_CENT)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("amount должен быть корректным десятичным числом") from exc

    if not normalized.is_finite() or normalized <= 0:
        raise ValueError("amount должен быть больше нуля")

    return normalized
