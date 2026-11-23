"""Валидация обязательного API-ключа в Settings."""

import pytest
from pydantic import ValidationError

from payment_service.config import MIN_API_KEY_LENGTH, Settings


def make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


@pytest.fixture(autouse=True)
def _no_env_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_KEY", raising=False)


def test_missing_api_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="api_key"):
        make_settings()


def test_placeholder_api_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="change-me"):
        make_settings(api_key="change-me")


@pytest.mark.parametrize("api_key", ["", "   "])
def test_blank_api_key_is_rejected(api_key: str) -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        make_settings(api_key=api_key)


def test_short_api_key_is_rejected() -> None:
    short_key = "x" * (MIN_API_KEY_LENGTH - 1)

    with pytest.raises(ValidationError, match="at least"):
        make_settings(api_key=short_key)


def test_strong_api_key_is_accepted() -> None:
    strong_key = "x" * MIN_API_KEY_LENGTH

    settings = make_settings(api_key=strong_key)

    assert settings.api_key.get_secret_value() == strong_key


def test_webhook_settings_have_safe_defaults() -> None:
    settings = make_settings(api_key="x" * MIN_API_KEY_LENGTH)

    assert settings.webhook_allow_http is False
    assert settings.webhook_allowed_host_names == frozenset()


def test_allowed_hosts_are_normalized() -> None:
    settings = make_settings(
        api_key="x" * MIN_API_KEY_LENGTH,
        webhook_allowed_hosts=" E2E-Webhook-Receiver. , localhost ",
    )

    assert settings.webhook_allowed_host_names == frozenset(
        {"e2e-webhook-receiver", "localhost"},
    )
