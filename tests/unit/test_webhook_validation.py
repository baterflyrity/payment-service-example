"""SSRF-валидация webhook_url на входе API."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from payment_service.config import settings
from payment_service.entrypoints.api.schemas import PaymentCreate


def make_payload(webhook_url: str) -> dict[str, object]:
    return {
        "amount": Decimal("125.50"),
        "currency": "RUB",
        "description": "Test payment",
        "metadata": {"order_id": "order-123"},
        "webhook_url": webhook_url,
    }


@pytest.fixture
def allow_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "webhook_allow_http", True)


@pytest.fixture
def deny_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "webhook_allow_http", False)


def test_https_public_url_is_allowed(deny_http: None) -> None:
    payload = PaymentCreate.model_validate(
        make_payload("https://merchant.example/webhooks/payments"),
    )

    assert str(payload.webhook_url) == (
        "https://merchant.example/webhooks/payments"
    )


def test_http_url_is_rejected_without_flag(deny_http: None) -> None:
    with pytest.raises(ValidationError, match="must use https"):
        PaymentCreate.model_validate(
            make_payload("http://merchant.example/webhooks/payments"),
        )


def test_http_url_is_allowed_with_flag(allow_http: None) -> None:
    payload = PaymentCreate.model_validate(
        make_payload("http://merchant.example/webhooks/payments"),
    )

    assert str(payload.webhook_url).startswith("http://")


@pytest.mark.parametrize(
    "webhook_url",
    [
        "https://127.0.0.1/webhook",
        "https://10.0.0.5/webhook",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/webhook",
        "https://[::ffff:127.0.0.1]/webhook",
        "https://localhost/webhook",
        "https://api.localhost/webhook",
    ],
)
def test_ip_literals_and_localhost_are_rejected(
    deny_http: None,
    webhook_url: str,
) -> None:
    with pytest.raises(ValidationError):
        PaymentCreate.model_validate(make_payload(webhook_url))


def test_userinfo_is_rejected(deny_http: None) -> None:
    with pytest.raises(ValidationError, match="user information"):
        PaymentCreate.model_validate(
            make_payload("https://user:password@merchant.example/webhook"),
        )
