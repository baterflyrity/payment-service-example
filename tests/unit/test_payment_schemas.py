from decimal import Decimal

import pytest
from pydantic import ValidationError

from payment_service.entrypoints.api.schemas import (
    MAX_METADATA_BYTES,
    MAX_METADATA_DEPTH,
    PaymentCreate,
)


def make_payload(**overrides: object) -> PaymentCreate:
    data: dict[str, object] = {
        "amount": "125.50",
        "currency": "RUB",
        "description": "Test payment",
        "metadata": {"order_id": "order-123"},
        "webhook_url": "https://example.com/webhooks/payments",
    }
    data.update(overrides)
    return PaymentCreate.model_validate(data)


def test_valid_payment_payload() -> None:
    payload = make_payload()

    assert payload.amount == Decimal("125.50")
    assert payload.currency == "RUB"
    assert payload.metadata == {"order_id": "order-123"}


@pytest.mark.parametrize("amount", ["0", "-1.00"])
def test_rejects_non_positive_amount(amount: str) -> None:
    with pytest.raises(ValidationError):
        make_payload(amount=amount)


def test_rejects_amount_with_too_many_decimal_places() -> None:
    with pytest.raises(ValidationError):
        make_payload(amount="10.123")


def test_rejects_unsupported_currency() -> None:
    with pytest.raises(ValidationError):
        make_payload(currency="GBP")


def test_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        make_payload(unexpected_field="value")


def test_rejects_non_json_safe_metadata() -> None:
    with pytest.raises(ValidationError):
        make_payload(metadata={"amount": float("nan")})


def test_rejects_metadata_over_16_kb() -> None:
    too_big = "x" * (MAX_METADATA_BYTES + 1)

    with pytest.raises(ValidationError, match="at most"):
        make_payload(metadata={"payload": too_big})


def test_accepts_metadata_of_exactly_16_kb() -> None:
    # Оставляем место на JSON-обёртку {"payload": ""}.
    overhead = len('{"payload": ""}')
    value = "x" * (MAX_METADATA_BYTES - overhead)

    payload = make_payload(metadata={"payload": value})

    assert payload.metadata["payload"] == value


def nested_metadata(depth: int) -> dict[str, object]:
    value: dict[str, object] = {"leaf": True}
    for _ in range(depth - 1):
        value = {"nested": value}
    return value


def test_accepts_metadata_at_max_depth() -> None:
    metadata = nested_metadata(MAX_METADATA_DEPTH)

    payload = make_payload(metadata=metadata)

    assert payload.metadata == metadata


def test_rejects_metadata_deeper_than_max_depth() -> None:
    metadata = nested_metadata(MAX_METADATA_DEPTH + 1)

    with pytest.raises(ValidationError, match="nested at most"):
        make_payload(metadata=metadata)


def test_rejects_description_longer_than_500() -> None:
    with pytest.raises(ValidationError):
        make_payload(description="x" * 501)
