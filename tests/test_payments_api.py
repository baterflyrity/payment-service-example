from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from payment_service.models import Outbox, Payment

PAYMENTS_URL = "/api/v1/payments"


def make_payload(**overrides: object) -> dict[str, object]:
    """Build a valid payment request, allowing individual fields to be changed."""

    data: dict[str, object] = {
        "amount": "125.50",
        "currency": "RUB",
        "description": "Test payment",
        "metadata": {"order_id": "order-123"},
        "webhook_url": "https://example.com/webhooks/payments",
    }
    data.update(overrides)
    return data


def auth_headers(api_key: str, idempotency_key: str) -> dict[str, str]:
    return {
        "X-API-Key": api_key,
        "Idempotency-Key": idempotency_key,
    }


async def create_payment(
    client: AsyncClient,
    api_key: str,
    idempotency_key: str = "test-payment-001",
    **payload_overrides: object,
):
    return await client.post(
        PAYMENTS_URL,
        headers=auth_headers(api_key, idempotency_key),
        json=make_payload(**payload_overrides),
    )


@pytest.mark.asyncio
async def test_create_payment_returns_202_and_writes_outbox(
    client: AsyncClient,
    api_key: str,
    db_connection: AsyncConnection,
) -> None:
    response = await create_payment(client, api_key)

    assert response.status_code == 202

    data = response.json()
    payment_id = UUID(data["payment_id"])

    assert data["status"] == "pending"
    assert data["created_at"]

    # The payment and its Outbox event must both exist.
    payment_count = await db_connection.scalar(
        select(func.count()).select_from(Payment),
    )
    outbox_count = await db_connection.scalar(
        select(func.count()).select_from(Outbox),
    )

    assert payment_count == 1
    assert outbox_count == 1

    event = (
        await db_connection.execute(
            select(
                Outbox.event_type,
                Outbox.aggregate_id,
                Outbox.payload,
            ),
        )
    ).one()

    assert event.event_type == "payments.new"
    assert event.aggregate_id == payment_id
    assert event.payload["payment_id"] == str(payment_id)


@pytest.mark.asyncio
async def test_get_payment_returns_details(
    client: AsyncClient,
    api_key: str,
) -> None:
    create_response = await create_payment(client, api_key)

    assert create_response.status_code == 202
    payment_id = create_response.json()["payment_id"]

    response = await client.get(
        f"{PAYMENTS_URL}/{payment_id}",
        headers={"X-API-Key": api_key},
    )

    assert response.status_code == 200

    data = response.json()
    assert data["payment_id"] == payment_id
    assert data["amount"] == "125.50"
    assert data["currency"] == "RUB"
    assert data["description"] == "Test payment"
    assert data["metadata"] == {"order_id": "order-123"}
    assert data["status"] == "pending"
    assert data["webhook_url"] == ("https://example.com/webhooks/payments")
    assert data["created_at"]
    assert data["processed_at"] is None


@pytest.mark.asyncio
async def test_get_unknown_payment_returns_404(
    client: AsyncClient,
    api_key: str,
) -> None:
    unknown_id = UUID("00000000-0000-0000-0000-000000000001")

    response = await client.get(
        f"{PAYMENTS_URL}/{unknown_id}",
        headers={"X-API-Key": api_key},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Payment not found"


@pytest.mark.asyncio
async def test_repeating_same_request_is_idempotent(
    client: AsyncClient,
    api_key: str,
    db_connection: AsyncConnection,
) -> None:
    headers = auth_headers(api_key, "idempotency-same-request")
    payload = make_payload()

    first = await client.post(
        PAYMENTS_URL,
        headers=headers,
        json=payload,
    )
    second = await client.post(
        PAYMENTS_URL,
        headers=headers,
        json=payload,
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["payment_id"] == second.json()["payment_id"]
    assert first.json()["created_at"] == second.json()["created_at"]

    payment_count = await db_connection.scalar(
        select(func.count()).select_from(Payment),
    )
    outbox_count = await db_connection.scalar(
        select(func.count()).select_from(Outbox),
    )

    assert payment_count == 1
    assert outbox_count == 1


@pytest.mark.asyncio
async def test_reusing_key_with_different_data_returns_409(
    client: AsyncClient,
    api_key: str,
    db_connection: AsyncConnection,
) -> None:
    key = "idempotency-different-request"

    first = await create_payment(client, api_key, key)
    second = await create_payment(
        client,
        api_key,
        key,
        amount="999.00",
    )

    assert first.status_code == 202
    assert second.status_code == 409
    assert "different request data" in second.json()["detail"]

    payment_count = await db_connection.scalar(
        select(func.count()).select_from(Payment),
    )
    outbox_count = await db_connection.scalar(
        select(func.count()).select_from(Outbox),
    )

    assert payment_count == 1
    assert outbox_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", f"{PAYMENTS_URL}/00000000-0000-0000-0000-000000000001"),
        ("POST", PAYMENTS_URL),
    ],
)
async def test_api_key_is_required(
    client: AsyncClient,
    method: str,
    path: str,
) -> None:
    if method == "POST":
        response = await client.post(
            path,
            headers={"Idempotency-Key": "unauthorized-test"},
            json=make_payload(),
        )
    else:
        response = await client.get(path)

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing API key"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"amount": "0"},
        {"amount": "-10.00"},
        {"currency": "GBP"},
    ],
)
async def test_invalid_payload_returns_422(
    client: AsyncClient,
    api_key: str,
    changes: dict[str, str],
) -> None:
    response = await create_payment(
        client,
        api_key,
        f"invalid-{changes}",
        **changes,
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_idempotency_key_is_required(
    client: AsyncClient,
    api_key: str,
) -> None:
    response = await client.post(
        PAYMENTS_URL,
        headers={"X-API-Key": api_key},
        json=make_payload(),
    )

    assert response.status_code == 422
