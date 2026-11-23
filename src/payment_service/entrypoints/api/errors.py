from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from payment_service.domain.errors import (
    DomainError,
    IdempotencyConflict,
    PaymentNotFound,
)


async def _idempotency_conflict_handler(
    _: Request,
    exc: IdempotencyConflict,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": (
                "Idempotency-Key has already been used with different request data"
            ),
        },
    )


async def _payment_not_found_handler(
    _: Request,
    exc: PaymentNotFound,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": "Payment not found"},
    )


async def _domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": str(exc)},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(IdempotencyConflict, _idempotency_conflict_handler)
    app.add_exception_handler(PaymentNotFound, _payment_not_found_handler)
    app.add_exception_handler(DomainError, _domain_error_handler)
