import pytest
from pydantic import SecretStr

from payment_service.config import settings


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Use a predictable API key without depending on the local .env."""

    test_key = "test-api-key"
    monkeypatch.setattr(settings, "api_key", SecretStr(test_key))
    return test_key
