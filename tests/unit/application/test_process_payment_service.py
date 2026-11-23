from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from types import TracebackType
from uuid import UUID, uuid4

import pytest

from payment_service.application.process_payment import ProcessPaymentService
from payment_service.domain.errors import PaymentNotFound
from payment_service.domain.events import PaymentCreated
from payment_service.domain.payment import Payment, PaymentStatus

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
PROCESSED_AT = datetime(2026, 11, 23, 12, 1, tzinfo=UTC)


@dataclass
class FakeState:
    payments: dict[UUID, Payment] = field(default_factory=dict)
    commits: int = 0


class FakePaymentRepository:
    def __init__(self, state: FakeState) -> None:
        self._state = state

    async def get_for_update(self, payment_id: UUID) -> Payment | None:
        return self._state.payments.get(payment_id)

    async def add(self, payment: Payment) -> None:
        self._state.payments[payment.id] = payment


class FakeUnitOfWork:
    def __init__(self, state: FakeState) -> None:
        self._state = state
        self.payments = FakePaymentRepository(state)

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


class FakeGateway:
    def __init__(self, result: bool) -> None:
        self.result = result
        self.calls: list[UUID] = []

    async def process(
        self,
        payment_id: UUID,
        amount: Decimal,
        currency: object,
    ) -> bool:
        del amount, currency
        self.calls.append(payment_id)
        return self.result


class FakeWebhookSender:
    def __init__(self, fail_with: Exception | None = None) -> None:
        self.sent: list[tuple[str, dict[str, object]]] = []
        self._fail_with = fail_with

    async def send(self, webhook_url: str, payload: dict[str, object]) -> None:
        if self._fail_with is not None:
            raise self._fail_with

        self.sent.append((webhook_url, payload))


def make_payment(final: bool = False) -> Payment:
    payment = Payment.create(
        amount=Decimal("125.50"),
        currency="RUB",
        description="Process payment test",
        metadata={"order_id": "42"},
        idempotency_key=f"process-{uuid4()}",
        request_hash="a" * 64,
        webhook_url="https://example.test/webhook",
        now=NOW,
    )

    if final:
        payment.mark_succeeded(PROCESSED_AT)

    return payment


def make_event(payment_id: UUID) -> PaymentCreated:
    return PaymentCreated(
        event_id=uuid4(),
        payment_id=payment_id,
        occurred_at=NOW,
    )


def make_service(
    state: FakeState,
    gateway: FakeGateway,
    webhook: FakeWebhookSender,
) -> ProcessPaymentService:
    return ProcessPaymentService(
        uow_factory=lambda: FakeUnitOfWork(state),
        gateway=gateway,
        webhook_sender=webhook,
        clock=lambda: PROCESSED_AT,
    )


@pytest.mark.asyncio
async def test_pending_payment_is_processed_once_and_webhook_is_sent() -> None:
    payment = make_payment()
    state = FakeState(payments={payment.id: payment})
    gateway = FakeGateway(result=True)
    webhook = FakeWebhookSender()
    event = make_event(payment.id)

    await make_service(state, gateway, webhook).execute(event)

    assert gateway.calls == [payment.id]
    assert state.commits == 1
    assert payment.status is PaymentStatus.SUCCEEDED
    assert payment.processed_at == PROCESSED_AT
    assert webhook.sent == [
        (
            payment.webhook_url,
            {
                "event_id": str(event.event_id),
                "payment_id": str(payment.id),
                "status": "succeeded",
                "amount": "125.50",
                "currency": "RUB",
                "processed_at": PROCESSED_AT.isoformat(),
            },
        ),
    ]


@pytest.mark.asyncio
async def test_failed_gateway_result_marks_payment_failed() -> None:
    payment = make_payment()
    state = FakeState(payments={payment.id: payment})
    gateway = FakeGateway(result=False)
    webhook = FakeWebhookSender()

    await make_service(state, gateway, webhook).execute(make_event(payment.id))

    assert payment.status is PaymentStatus.FAILED
    assert webhook.sent[0][1]["status"] == "failed"


@pytest.mark.asyncio
async def test_final_payment_is_not_processed_again() -> None:
    payment = make_payment(final=True)
    state = FakeState(payments={payment.id: payment})
    gateway = FakeGateway(result=False)
    webhook = FakeWebhookSender()
    event = make_event(payment.id)

    await make_service(state, gateway, webhook).execute(event)

    assert gateway.calls == []
    assert state.commits == 0
    assert payment.status is PaymentStatus.SUCCEEDED
    assert payment.processed_at == PROCESSED_AT
    assert webhook.sent[0][1]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_webhook_error_propagates_after_status_is_persisted() -> None:
    payment = make_payment()
    state = FakeState(payments={payment.id: payment})
    gateway = FakeGateway(result=True)
    webhook = FakeWebhookSender(fail_with=RuntimeError("webhook is down"))

    with pytest.raises(RuntimeError, match="webhook is down"):
        await make_service(state, gateway, webhook).execute(
            make_event(payment.id),
        )

    assert gateway.calls == [payment.id]
    assert state.commits == 1
    assert payment.status is PaymentStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_unknown_payment_raises_not_found() -> None:
    state = FakeState()
    gateway = FakeGateway(result=True)
    webhook = FakeWebhookSender()

    with pytest.raises(PaymentNotFound):
        await make_service(state, gateway, webhook).execute(
            make_event(uuid4()),
        )

    assert gateway.calls == []
    assert webhook.sent == []
