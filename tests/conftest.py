import os

# Settings() валидируется при импорте и требует сильный API_KEY. Unit-тесты не
# должны зависеть от локального .env, поэтому задаём тестовый ключ заранее.
os.environ.setdefault("API_KEY", "test-api-key-0123456789abcdef0123456789abcdef")

import pytest  # noqa: E402
from pydantic import SecretStr  # noqa: E402

from payment_service.config import settings  # noqa: E402


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Use a predictable API key without depending on the local .env."""

    test_key = "test-api-key-0123456789abcdef0123456789abcdef"
    monkeypatch.setattr(settings, "api_key", SecretStr(test_key))
    return test_key
