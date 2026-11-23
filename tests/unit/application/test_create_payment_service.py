from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from types import TracebackType
from typing import Any
from uuid import UUID

import pytest

from payment_service.application.commands import CreatePaymentCommand
from payment_service.application.create_payment import CreatePaymentService
from payment_service.application.idempotency import calculate_request_hash
from payment_service.domain.errors import (
    DuplicateIdempotencyKey,
    IdempotencyConflict,
)
from payment_service.domain.events import PaymentCreated
from payment_service.domain.payment import Currency, Payment

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


@dataclass
class FakeState:
    by_key: dict[str, Payment] = field(default_factory=dict)
    events: list[PaymentCreated] = field(default_factory=list)
    # Симуляция гонки: параллельный победитель появляется на попытке вставки.
    hidden_winner: Payment | None = None


class FakePaymentRepository:
    def __init__(self, state: FakeState) -> None:
        self._state = state

    async def add(self, payment: Payment) -> None:
        winner = self._state.hidden_winner
        if winner is not None:
            self._state.hidden_winner = None
            self._state.by_key[winner.idempotency_key] = winner
            raise DuplicateIdempotencyKey(payment.idempotency_key)

        if payment.idempotency_key in self._state.by_key:
            raise DuplicateIdempotencyKey(payment.idempotency_key)

        self._state.by_key[payment.idempotency_key] = payment

    async def get(self, payment_id: UUID) -> Payment | None:
        return next(
            (p for p in self._state.by_key.values() if p.id == payment_id),
            None,
        )

    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        return self._state.by_key.get(idempotency_key)

    async def get_for_update(self, payment_id: UUID) -> Payment | None:
        return await self.get(payment_id)


class FakeOutboxRepository:
    def __init__(self, state: FakeState) -> None:
        self._state = state

    async def add(self, event: PaymentCreated) -> None:
        self._state.events.append(event)


class FakeUnitOfWork:
    def __init__(self, state: FakeState) -> None:
        self.payments = FakePaymentRepository(state)
        self.outbox = FakeOutboxRepository(state)

    async def __aenter__(self) -> FakeUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def make_command(**overrides: Any) -> CreatePaymentCommand:
    data: dict[str, Any] = {
        "amount": Decimal("125.50"),
        "currency": Currency.RUB,
        "description": "Test payment",
        "metadata": {"order_id": "order-123"},
        "webhook_url": "https://example.com/webhooks/payments",
        "idempotency_key": "unit-key-1",
    }
    data.update(overrides)
    return CreatePaymentCommand(**data)


def make_service(state: FakeState) -> CreatePaymentService:
    return CreatePaymentService(
        uow_factory=lambda: FakeUnitOfWork(state),
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_new_payment_is_stored_and_emits_one_event() -> None:
    state = FakeState()
    command = make_command()

    payment, created = await make_service(state).execute(command)

    assert created is True
    assert payment.status.value == "pending"
    assert payment.created_at == NOW
    assert state.by_key == {command.idempotency_key: payment}
    assert len(state.events) == 1
    assert state.events[0].payment_id == payment.id


@pytest.mark.asyncio
async def test_repeat_returns_same_payment_without_new_event() -> None:
    state = FakeState()
    service = make_service(state)
    command = make_command()

    first, first_created = await service.execute(command)
    second, second_created = await service.execute(command)

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert len(state.by_key) == 1
    assert len(state.events) == 1


@pytest.mark.asyncio
async def test_different_body_raises_idempotency_conflict() -> None:
    state = FakeState()
    service = make_service(state)

    await service.execute(make_command())

    with pytest.raises(IdempotencyConflict):
        await service.execute(make_command(amount=Decimal("999.00")))

    assert len(state.by_key) == 1
    assert len(state.events) == 1


@pytest.mark.asyncio
async def test_race_returns_payment_created_by_parallel_transaction() -> None:
    state = FakeState()
    command = make_command()

    winner = Payment.create(
        amount=command.amount,
        currency=command.currency,
        description=command.description,
        metadata=command.metadata,
        idempotency_key=command.idempotency_key,
        request_hash=calculate_request_hash(command),
        webhook_url=command.webhook_url,
        now=NOW,
    )
    state.hidden_winner = winner

    payment, created = await make_service(state).execute(command)

    assert created is False
    assert payment.id == winner.id
    assert state.by_key[command.idempotency_key] is winner
    assert state.events == []
