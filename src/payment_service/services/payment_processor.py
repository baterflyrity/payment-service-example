import asyncio
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payment_service.db import SessionFactory
from payment_service.models import Payment
from payment_service.schemas.events import PaymentCreatedEvent

PaymentResult = Literal["succeeded", "failed"]
GatewaySimulator = Callable[[], Awaitable[PaymentResult]]


class PaymentNotFoundError(Exception):
    """The event references a payment that does not exist."""


async def simulate_payment_gateway() -> PaymentResult:
    """Simulate an external payment gateway."""

    await asyncio.sleep(random.uniform(2.0, 5.0))

    if random.random() < 0.9:
        return "succeeded"

    return "failed"


async def process_payment_event(
    event: PaymentCreatedEvent,
    *,
    http_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession] = SessionFactory,
    gateway: GatewaySimulator = simulate_payment_gateway,
) -> None:
    """Process a payment once and deliver its result by webhook.

    If webhook delivery fails, the message can be retried without processing
    a payment that already has a final status again.
    """

    # Read the payment before calling the simulated external gateway.
    async with session_factory() as session:
        payment = await session.get(Payment, event.payment_id)

        if payment is None:
            raise PaymentNotFoundError(
                f"Payment {event.payment_id} does not exist",
            )

        needs_processing = payment.status == "pending"

    gateway_result: PaymentResult | None = None

    if needs_processing:
        # Do not keep a database transaction open while waiting on the gateway.
        gateway_result = await gateway()

    # Apply the result under a row lock. A duplicate event must not overwrite
    # a final status with another result.
    async with session_factory() as session:
        async with session.begin():
            payment = await session.scalar(
                select(Payment).where(Payment.id == event.payment_id).with_for_update(),
            )

            if payment is None:
                raise PaymentNotFoundError(
                    f"Payment {event.payment_id} does not exist",
                )

            if payment.status == "pending":
                if gateway_result is None:
                    raise RuntimeError(
                        "Payment is pending but no gateway result is available",
                    )

                payment.status = gateway_result
                payment.processed_at = datetime.now(UTC)

            elif payment.status not in {"succeeded", "failed"}:
                raise RuntimeError(
                    f"Unexpected payment status: {payment.status}",
                )

            # Copy the values needed for the webhook while the ORM object
            # is attached to the session.
            payment_status = payment.status
            payment_amount: Decimal = payment.amount
            payment_currency = payment.currency
            payment_processed_at = payment.processed_at
            webhook_url = payment.webhook_url

            webhook_payload = {
                "event_id": str(event.event_id),
                "event_type": f"payment.{payment_status}",
                "payment": {
                    "id": str(payment.id),
                    "amount": format(payment_amount, ".2f"),
                    "currency": payment_currency,
                    "status": payment_status,
                    "processed_at": (payment_processed_at.isoformat() if payment_processed_at is not None else None),
                },
            }

    # This happens after the transaction commits. A webhook failure must not
    # roll back the payment result or cause the gateway to run again.
    response = await http_client.post(
        webhook_url,
        json=webhook_payload,
    )
    response.raise_for_status()
