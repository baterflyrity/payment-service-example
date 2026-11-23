from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from payment_service.config import settings
from payment_service.entrypoints.api.errors import register_exception_handlers
from payment_service.entrypoints.api.health import router as health_router
from payment_service.entrypoints.api.routers import router as payments_router
from payment_service.infrastructure.db.session import engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    """Собрать приложение.

    Swagger UI и ``/openapi.json`` отключены по умолчанию: они раскрывают схему
    API без ``X-API-Key``, а требование ТЗ — ключ на всех эндпоинтах.
    Включаются флагом ``ENABLE_DOCS=true`` только для локальной разработки.
    """

    docs_enabled = settings.enable_docs

    app = FastAPI(
        title="Payment Processing Service Example",
        description="Asynchronous payment processing API",
        version="0.1.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(payments_router)

    return app


app = create_app()
