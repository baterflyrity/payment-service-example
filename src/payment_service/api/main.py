import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from payment_service.api.payments import router as payments_router
from payment_service.db import engine
from payment_service.workers.outbox_publisher import run_outbox_publisher


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    stop_event = asyncio.Event()

    publisher_task = asyncio.create_task(
        run_outbox_publisher(stop_event),
        name="outbox-publisher",
    )

    try:
        yield
    finally:
        stop_event.set()

        try:
            await publisher_task
        finally:
            await engine.dispose()


app = FastAPI(
    title="Payment Processing Service Example",
    description="Asynchronous payment processing API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(payments_router)
