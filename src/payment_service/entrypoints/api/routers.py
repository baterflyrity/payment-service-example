from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status

from payment_service.application.commands import CreatePaymentCommand
from payment_service.application.create_payment import CreatePaymentService
from payment_service.application.get_payment import GetPaymentService
from payment_service.container import (
    get_create_payment_service,
    get_payment_service,
)
from payment_service.domain.payment import Currency
from payment_service.entrypoints.api.deps import require_api_key
from payment_service.entrypoints.api.schemas import (
    PaymentCreate,
    PaymentCreated,
    PaymentDetail,
)

router = APIRouter(
    prefix="/api/v1/payments",
    tags=["payments"],
    dependencies=[Depends(require_api_key)],
)


@router.post(
    "",
    response_model=PaymentCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_payment(
    payload: PaymentCreate,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
    service: Annotated[CreatePaymentService, Depends(get_create_payment_service)],
) -> PaymentCreated:
    """Create a payment; idempotency and outbox live in the application layer."""

    normalized_key = idempotency_key.strip()
    if not normalized_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key must not be empty",
        )

    command = CreatePaymentCommand(
        amount=payload.amount,
        currency=Currency(payload.currency),
        description=payload.description,
        metadata=payload.metadata,
        webhook_url=str(payload.webhook_url),
        idempotency_key=normalized_key,
    )

    payment, _ = await service.execute(command)

    return PaymentCreated(
        payment_id=payment.id,
        status=payment.status,
        created_at=payment.created_at,
    )


@router.get(
    "/{payment_id}",
    response_model=PaymentDetail,
)
async def get_payment(
    payment_id: UUID,
    service: Annotated[GetPaymentService, Depends(get_payment_service)],
) -> PaymentDetail:
    """Return detailed information about a payment."""

    payment = await service.execute(payment_id)

    return PaymentDetail(
        payment_id=payment.id,
        amount=payment.amount,
        currency=payment.currency,
        description=payment.description,
        metadata=payment.metadata,
        status=payment.status,
        webhook_url=payment.webhook_url,
        created_at=payment.created_at,
        processed_at=payment.processed_at,
    )
