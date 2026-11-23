from decimal import Decimal

from payment_service.application.commands import CreatePaymentCommand
from payment_service.application.idempotency import calculate_request_hash
from payment_service.domain.payment import Currency


def make_command(
    amount: str,
    metadata: dict[str, object],
) -> CreatePaymentCommand:
    return CreatePaymentCommand(
        amount=Decimal(amount),
        currency=Currency.RUB,
        description="Test payment",
        metadata=metadata,
        webhook_url="https://example.com/webhooks/payments",
        idempotency_key="idempotency-test-key",
    )


def test_hash_is_stable_for_equivalent_payloads() -> None:
    first = make_command(
        "10.0",
        {"order": {"id": 123, "source": "test"}},
    )
    second = make_command(
        "10.00",
        {"order": {"source": "test", "id": 123}},
    )

    assert calculate_request_hash(first) == calculate_request_hash(second)


def test_hash_changes_when_request_data_changes() -> None:
    first = make_command("10.00", {"order_id": "order-1"})
    second = make_command("11.00", {"order_id": "order-1"})

    assert calculate_request_hash(first) != calculate_request_hash(second)
