from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from payment_service.domain import (
    Currency,
    IdempotencyConflict,
    InvalidStatusTransition,
    Payment,
    PaymentCreated,
    PaymentStatus,
)

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


def make_payment(**overrides: object) -> Payment:
    params: dict[str, object] = {
        "amount": Decimal("100.00"),
        "currency": "RUB",
        "description": "Оплата заказа",
        "metadata": {"order_id": "42"},
        "idempotency_key": "key-1",
        "request_hash": "hash-1",
        "webhook_url": "https://example.com/webhook",
        "now": NOW,
    }
    params.update(overrides)
    return Payment.create(**params)  # type: ignore[arg-type]


class TestPaymentCreate:
    def test_creates_pending_payment_with_fields(self) -> None:
        payment = make_payment()

        assert payment.status is PaymentStatus.PENDING
        assert payment.processed_at is None
        assert payment.is_final is False
        assert payment.currency is Currency.RUB
        assert payment.created_at == NOW
        assert payment.metadata == {"order_id": "42"}

    @pytest.mark.parametrize(
        ("amount", "expected"),
        [
            ("10", Decimal("10.00")),
            ("10.005", Decimal("10.00")),
            ("10.006", Decimal("10.01")),
            (Decimal("0.999"), Decimal("1.00")),
            (5, Decimal("5.00")),
        ],
    )
    def test_quantizes_amount_to_two_places(
        self, amount: object, expected: Decimal
    ) -> None:
        assert make_payment(amount=amount).amount == expected

    @pytest.mark.parametrize("amount", ["0", "-1", "-0.01", "NaN", "Infinity"])
    def test_rejects_non_positive_or_non_finite_amount(self, amount: str) -> None:
        with pytest.raises(ValueError):
            make_payment(amount=amount)

    def test_rejects_unknown_currency(self) -> None:
        with pytest.raises(ValueError):
            make_payment(currency="GBP")

    def test_defaults_metadata_to_empty_dict(self) -> None:
        assert make_payment(metadata=None).metadata == {}

    def test_metadata_is_copied(self) -> None:
        source = {"order_id": "42"}
        payment = make_payment(metadata=source)
        source["order_id"] = "changed"

        assert payment.metadata == {"order_id": "42"}

    @pytest.mark.parametrize("currency", list(Currency))
    def test_accepts_each_currency(self, currency: Currency) -> None:
        assert make_payment(currency=currency).currency is currency


class TestStatusTransitions:
    def test_marks_succeeded(self) -> None:
        payment = make_payment()
        processed_at = NOW + timedelta(seconds=3)

        payment.mark_succeeded(processed_at)

        assert payment.status is PaymentStatus.SUCCEEDED
        assert payment.processed_at == processed_at
        assert payment.is_final is True

    def test_marks_failed(self) -> None:
        payment = make_payment()

        payment.mark_failed(NOW)

        assert payment.status is PaymentStatus.FAILED
        assert payment.processed_at == NOW
        assert payment.is_final is True

    @pytest.mark.parametrize("target", ["succeeded", "failed"])
    def test_rejects_any_transition_from_final_status(self, target: str) -> None:
        payment = make_payment()
        payment.mark_succeeded(NOW)

        with pytest.raises(InvalidStatusTransition):
            if target == "succeeded":
                payment.mark_succeeded(NOW)
            else:
                payment.mark_failed(NOW)

        assert payment.status is PaymentStatus.SUCCEEDED
        assert payment.processed_at == NOW

    def test_failed_payment_cannot_succeed(self) -> None:
        payment = make_payment()
        payment.mark_failed(NOW)

        with pytest.raises(InvalidStatusTransition):
            payment.mark_succeeded(NOW)


class TestIdempotency:
    def test_same_request_hash_passes(self) -> None:
        make_payment(request_hash="hash-1").ensure_same_request("hash-1")

    def test_different_request_hash_conflicts(self) -> None:
        payment = make_payment(request_hash="hash-1")

        with pytest.raises(IdempotencyConflict) as exc_info:
            payment.ensure_same_request("hash-2")

        assert exc_info.value.idempotency_key == "key-1"


class TestEvents:
    def test_create_registers_payment_created_event(self) -> None:
        payment = make_payment()

        events = payment.pull_events()

        assert len(events) == 1
        event = events[0]
        assert isinstance(event, PaymentCreated)
        assert event.payment_id == payment.id
        assert event.occurred_at == payment.created_at
        assert event.event_type == "payment.created"
        assert event.event_id == event.event_id  # стабильный UUID

    def test_pull_events_drains_registered_events(self) -> None:
        payment = make_payment()

        first = payment.pull_events()
        second = payment.pull_events()

        assert len(first) == 1
        assert second == []

    def test_each_payment_gets_unique_ids_and_events(self) -> None:
        first = make_payment()
        second = make_payment()

        assert first.id != second.id
        assert first.pull_events()[0].event_id != second.pull_events()[0].event_id

    def test_status_change_does_not_emit_events(self) -> None:
        payment = make_payment()
        payment.pull_events()

        payment.mark_succeeded(NOW)

        assert payment.pull_events() == []


class TestPaymentNotFound:
    def test_domain_error_is_exported(self) -> None:
        from payment_service.domain import PaymentNotFound

        payment_id = uuid4()
        error = PaymentNotFound(payment_id)

        assert error.payment_id == payment_id
        assert str(payment_id) in str(error)
