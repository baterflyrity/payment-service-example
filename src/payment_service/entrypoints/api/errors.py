from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from payment_service.domain.errors import (
    DomainError,
    IdempotencyConflict,
    PaymentNotFound,
)

_HTTP_ERROR_CODES = {
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "validation_error",
    status.HTTP_503_SERVICE_UNAVAILABLE: "not_ready",
}


def error_response(
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Единый формат ошибок: ``{"error": {"code": ..., "message": ...}}``."""

    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers=headers,
    )


async def _idempotency_conflict_handler(
    _: Request,
    exc: IdempotencyConflict,
) -> JSONResponse:
    return error_response(
        status.HTTP_409_CONFLICT,
        "idempotency_conflict",
        "Idempotency-Key has already been used with different request data",
    )


async def _payment_not_found_handler(
    _: Request,
    exc: PaymentNotFound,
) -> JSONResponse:
    return error_response(
        status.HTTP_404_NOT_FOUND,
        "not_found",
        "Payment not found",
    )


async def _domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    return error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "domain_error",
        str(exc),
    )


def _validation_message(errors: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for error in errors:
        location = ".".join(
            str(item) for item in error.get("loc", ()) if item != "body"
        )
        message = error.get("msg", "invalid value")
        parts.append(f"{location}: {message}" if location else str(message))
    return "; ".join(parts) or "Request validation failed"


async def _validation_error_handler(
    _: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "validation_error",
        _validation_message(list(exc.errors())),
    )


async def _http_error_handler(
    _: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    code = _HTTP_ERROR_CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return error_response(exc.status_code, code, message, exc.headers)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(IdempotencyConflict, _idempotency_conflict_handler)
    app.add_exception_handler(PaymentNotFound, _payment_not_found_handler)
    app.add_exception_handler(DomainError, _domain_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
