from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID, uuid4

import pytest

from payment_service.application.relay_outbox import RelayOutboxService
from payment_service.domain.events import OutboxMessage, PaymentCreated

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


@dataclass
class FakeState:
    messages: list[OutboxMessage] = field(default_factory=list)
    published: set[UUID] = field(default_factory=set)
    attempts: dict[UUID, int] = field(default_factory=dict)
    last_errors: dict[UUID, str] = field(default_factory=dict)
    commits: int = 0

    def pending(self) -> list[OutboxMessage]:
        return [message for message in self.messages if message.id not in self.published]


class FakeOutboxRepository:
    def __init__(self, state: FakeState) -> None:
        self._state = state

    async def lock_unpublished(self, limit: int) -> list[OutboxMessage]:
        return self._state.pending()[:limit]

    async def mark_published(self, ids: list[UUID]) -> None:
        self._state.published.update(ids)

    async def mark_failed(self, id: UUID, error: str) -> None:
        self._state.attempts[id] = self._state.attempts.get(id, 0) + 1
        self._state.last_errors[id] = error


class FakeUnitOfWork:
    def __init__(self, state: FakeState) -> None:
        self.outbox = FakeOutboxRepository(state)
        self._state = state

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
        self._state.commits += 1

    async def rollback(self) -> None:
        return None


class FakePublisher:
    def __init__(self, fail_with: Exception | None = None) -> None:
        self.events: list[PaymentCreated] = []
        self._fail_with = fail_with

    async def publish(self, event: PaymentCreated) -> None:
        if self._fail_with is not None:
            raise self._fail_with

        self.events.append(event)


def add_message(state: FakeState, payment_id: UUID | None = None) -> OutboxMessage:
    payment_id = payment_id or uuid4()
    event_id = uuid4()
    event = OutboxMessage(
        id=uuid4(),
        event_id=event_id,
        event_type="payment.created",
        payload={
            "event_id": str(event_id),
            "payment_id": str(payment_id),
            "occurred_at": NOW.isoformat(),
        },
    )
    state.messages.append(event)
    return event


def make_service(
    state: FakeState,
    publisher: FakePublisher,
    batch_size: int = 100,
) -> RelayOutboxService:
    return RelayOutboxService(
        uow_factory=lambda: FakeUnitOfWork(state),
        publisher=publisher,
        batch_size=batch_size,
    )


@pytest.mark.asyncio
async def test_success_publishes_and_marks_event() -> None:
    state = FakeState()
    message = add_message(state)
    publisher = FakePublisher()

    published = await make_service(state, publisher).run_once()

    assert published == 1
    assert len(publisher.events) == 1
    assert publisher.events[0].event_id == message.event_id
    assert publisher.events[0].payment_id == UUID(message.payload["payment_id"])
    assert state.published == {message.id}
    assert state.attempts == {}
    assert state.commits == 1


@pytest.mark.asyncio
async def test_broker_failure_keeps_event_pending_and_retries_next_run() -> None:
    state = FakeState()
    message = add_message(state)
    failing_publisher = FakePublisher(fail_with=RuntimeError("RabbitMQ unavailable"))

    published = await make_service(state, failing_publisher).run_once()

    assert published == 0
    assert failing_publisher.events == []
    assert state.published == set()
    assert state.attempts == {message.id: 1}
    assert "RabbitMQ unavailable" in state.last_errors[message.id]

    # Брокер восстановился: следующий проход публикует то же событие.
    publisher = FakePublisher()
    published = await make_service(state, publisher).run_once()

    assert published == 1
    assert [event.event_id for event in publisher.events] == [message.event_id]
    assert state.published == {message.id}


@pytest.mark.asyncio
async def test_publishes_at_most_batch_size_events() -> None:
    state = FakeState()
    add_message(state)
    second = add_message(state)
    publisher = FakePublisher()

    published = await make_service(state, publisher, batch_size=1).run_once()

    assert published == 1
    assert len(publisher.events) == 1
    assert len(state.pending()) == 1
    assert state.pending()[0].id == second.id

    published = await make_service(state, publisher, batch_size=1).run_once()

    assert published == 1
    assert state.pending() == []


@pytest.mark.asyncio
async def test_rejects_non_positive_batch_size() -> None:
    with pytest.raises(ValueError):
        RelayOutboxService(
            uow_factory=lambda: FakeUnitOfWork(FakeState()),
            publisher=FakePublisher(),
            batch_size=0,
        )
