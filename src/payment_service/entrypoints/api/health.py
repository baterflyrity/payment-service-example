from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from payment_service.infrastructure.db.session import ping_database

router = APIRouter(tags=["health"])

DatabaseCheck = Callable[[], Awaitable[None]]


def get_database_check() -> DatabaseCheck:
    """Подменяемая проверка БД (в тестах — без реального подключения)."""

    return ping_database


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: процесс жив и принимает запросы, БД не проверяется."""

    return {"status": "ok"}


@router.get("/health/ready", response_model=None)
async def ready(
    check_database: Annotated[DatabaseCheck, Depends(get_database_check)],
) -> dict[str, str] | JSONResponse:
    """Readiness: БД доступна, сервис готов обслуживать запросы."""

    try:
        await check_database()
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": {
                    "code": "not_ready",
                    "message": "Database is unavailable",
                },
            },
        )

    return {"status": "ready", "database": "ok"}
