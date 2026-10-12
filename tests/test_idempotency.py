from payment_service.schemas.payment import PaymentCreate
from payment_service.services.idempotency import calculate_request_hash


def make_payload(amount: str, metadata: dict[str, object]) -> PaymentCreate:
    return PaymentCreate(
        amount=amount,
        currency="RUB",
        description="Test payment",
        metadata=metadata,
        webhook_url="https://example.com/webhooks/payments",
    )


def test_hash_is_stable_for_equivalent_payloads() -> None:
    first = make_payload(
        "10.0",
        {"order": {"id": 123, "source": "test"}},
    )
    second = make_payload(
        "10.00",
        {"order": {"source": "test", "id": 123}},
    )

    assert calculate_request_hash(first) == calculate_request_hash(second)


def test_hash_changes_when_request_data_changes() -> None:
    first = make_payload("10.00", {"order_id": "order-1"})
    second = make_payload("11.00", {"order_id": "order-1"})

    assert calculate_request_hash(first) != calculate_request_hash(second)
