import secrets
from typing import Annotated

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from payment_service.config import settings

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Static API key required for all payment endpoints.",
)


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
