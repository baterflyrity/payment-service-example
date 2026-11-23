import secrets
from typing import Annotated

from fastapi import Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from payment_service.config import settings

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Static API key required for all payment endpoints.",
)


async def require_idempotency_key(
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", max_length=255),
    ],
) -> str:
    """Нормализовать ``Idempotency-Key`` и отклонить пустое значение.

    Проверка живёт в слое валидации, чтобы роутер оставался только маппингом
    DTO → команда → сервис → DTO. Ошибка проходит через общий обработчик
    исключений и возвращается в формате ``{"error": {...}}``.
    """

    normalized = idempotency_key.strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Idempotency-Key must not be empty",
        )
    return normalized


async def require_api_key(
    api_key: Annotated[str | None, Security(api_key_header)],
) -> None:
    expected_key = settings.api_key.get_secret_value()
    if api_key is None or not secrets.compare_digest(
        api_key.encode("utf-8"),
        expected_key.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "APIKey"},
        )
