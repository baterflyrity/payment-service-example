from decimal import Decimal

import pytest
from pydantic import ValidationError

from payment_service.schemas.payment import PaymentCreate


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
