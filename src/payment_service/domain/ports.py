from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from types import TracebackType
from typing import Any, Protocol, Self
from uuid import UUID

from payment_service.domain.events import OutboxMessage, PaymentCreated
from payment_service.domain.payment import Currency, Payment


class PaymentRepository(Protocol):
    async def add(self, payment: Payment) -> None: ...

    async def get(self, payment_id: UUID) -> Payment | None: ...

    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None: ...

    async def get_for_update(self, payment_id: UUID) -> Payment | None: ...


class OutboxRepository(Protocol):
    async def add(self, event: PaymentCreated) -> None: ...

    async def lock_unpublished(self, limit: int) -> Sequence[OutboxMessage]: ...

    async def mark_published(self, ids: Sequence[UUID]) -> None: ...

    async def mark_failed(self, id: UUID, error: str) -> None: ...


class UnitOfWork(Protocol):
    payments: PaymentRepository
    outbox: OutboxRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class PaymentGateway(Protocol):
    async def process(
        self, payment_id: UUID, amount: Decimal, currency: Currency
    ) -> bool: ...


class WebhookSender(Protocol):
    async def send(self, webhook_url: str, payload: Mapping[str, Any]) -> None: ...


class EventPublisher(Protocol):
    async def publish(self, event: PaymentCreated) -> None: ...
