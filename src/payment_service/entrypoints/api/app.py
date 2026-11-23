from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from payment_service.entrypoints.api.errors import register_exception_handlers
from payment_service.entrypoints.api.routers import router as payments_router
from payment_service.infrastructure.db.session import engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Payment Processing Service Example",
        description="Asynchronous payment processing API",
        version="0.1.0",
        lifespan=lifespan,
    )

    register_exception_handlers(app)
    app.include_router(payments_router)

    return app


app = create_app()
