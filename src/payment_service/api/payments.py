from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.api.dependencies import require_api_key
from payment_service.db import get_session
from payment_service.models import Outbox, Payment
from payment_service.schemas.payment import (
    PaymentCreate,
    PaymentCreated,
    PaymentDetail,
)
from payment_service.services.idempotency import calculate_request_hash

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
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PaymentCreated:
    """Create a payment and atomically record its Outbox event."""

    normalized_key = idempotency_key.strip()

    if not normalized_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key must not be empty",
        )

    try:
        request_hash = calculate_request_hash(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Metadata must contain valid JSON values",
        ) from exc

    payment_id = uuid4()
    event_id = uuid4()

    async with session.begin():
        statement = (
            pg_insert(Payment)
            .values(
                id=payment_id,
                amount=payload.amount,
                currency=payload.currency,
                description=payload.description,
                metadata_json=payload.metadata,
                status="pending",
                idempotency_key=normalized_key,
                request_hash=request_hash,
                webhook_url=str(payload.webhook_url),
            )
            .on_conflict_do_nothing(
                index_elements=[Payment.idempotency_key],
            )
            .returning(Payment.id, Payment.created_at)
        )

        inserted = (await session.execute(statement)).one_or_none()

        if inserted is not None:
            session.add(
                Outbox(
                    id=event_id,
                    event_type="payments.new",
                    aggregate_id=payment_id,
                    payload={
                        "event_id": str(event_id),
                        "payment_id": str(payment_id),
                    },
                ),
            )

            await session.flush()

            response = PaymentCreated(
                payment_id=inserted.id,
                status="pending",
                created_at=inserted.created_at,
            )
        else:
            existing = await session.scalar(
                select(Payment).where(
                    Payment.idempotency_key == normalized_key,
                ),
            )

            if existing is None:
                # Is in race condition?
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Could not resolve the idempotency key; retry the request",
                )

            if existing.request_hash != request_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=("Idempotency-Key has already been used with different request data"),
                )

            response = PaymentCreated(
                payment_id=existing.id,
                status=existing.status,
                created_at=existing.created_at,
            )

    return response


@router.get(
    "/{payment_id}",
    response_model=PaymentDetail,
)
async def get_payment(
    payment_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PaymentDetail:
    """Return detailed information about a payment."""

    payment = await session.scalar(
        select(Payment).where(Payment.id == payment_id),
    )

    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )

    return PaymentDetail(
        payment_id=payment.id,
        amount=payment.amount,
        currency=payment.currency,
        description=payment.description,
        metadata=payment.metadata_json,
        status=payment.status,
        webhook_url=payment.webhook_url,
        created_at=payment.created_at,
        processed_at=payment.processed_at,
    )
