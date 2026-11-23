from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from payment_service.entrypoints.api import health as health_module
from payment_service.entrypoints.api.app import app as fastapi_app
from payment_service.infrastructure.db.orm import OutboxORM as Outbox
from payment_service.infrastructure.db.orm import PaymentORM as Payment

pytestmark = pytest.mark.integration

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

    assert event.event_type == "payment.created"
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
    assert response.json() == {
        "error": {"code": "not_found", "message": "Payment not found"},
    }


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
    body = second.json()
    assert body["error"]["code"] == "idempotency_conflict"
    assert "different request data" in body["error"]["message"]

    payment_count = await db_connection.scalar(
        select(func.count()).select_from(Payment),
    )
    outbox_count = await db_connection.scalar(
        select(func.count()).select_from(Outbox),
    )

    assert payment_count == 1
    assert outbox_count == 1


API_KEY_ERROR = {
    "error": {
        "code": "unauthorized",
        "message": "Invalid or missing API key",
    },
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", f"{PAYMENTS_URL}/00000000-0000-0000-0000-000000000001"),
        ("POST", PAYMENTS_URL),
    ],
)
@pytest.mark.parametrize("api_key_header", [None, "wrong-api-key"])
async def test_api_key_is_required(
    client: AsyncClient,
    method: str,
    path: str,
    api_key_header: str | None,
) -> None:
    headers = {"Idempotency-Key": "unauthorized-test"}
    if api_key_header is not None:
        headers["X-API-Key"] = api_key_header

    if method == "POST":
        response = await client.post(
            path,
            headers=headers,
            json=make_payload(),
        )
    else:
        response = await client.get(path, headers=headers)

    assert response.status_code == 401
    assert response.json() == API_KEY_ERROR


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
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        {"payload": "x" * (16 * 1024 + 1)},
        {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}},
    ],
    ids=["too-large", "too-deep"],
)
async def test_oversized_or_too_deep_metadata_returns_422(
    client: AsyncClient,
    api_key: str,
    metadata: dict[str, object],
) -> None:
    response = await create_payment(
        client,
        api_key,
        "invalid-metadata",
        metadata=metadata,
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "webhook_url",
    [
        "http://rabbitmq:15672/",
        "https://169.254.169.254/latest/meta-data",
        "https://localhost/webhook",
        "https://user:pass@example.com/webhook",
    ],
)
async def test_unsafe_webhook_url_returns_422(
    client: AsyncClient,
    api_key: str,
    webhook_url: str,
) -> None:
    response = await create_payment(
        client,
        api_key,
        "invalid-webhook-url",
        webhook_url=webhook_url,
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"


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
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.asyncio
@pytest.mark.parametrize("idempotency_key", ["", "   "])
async def test_empty_idempotency_key_returns_422(
    client: AsyncClient,
    api_key: str,
    idempotency_key: str,
) -> None:
    response = await client.post(
        PAYMENTS_URL,
        headers={
            "X-API-Key": api_key,
            "Idempotency-Key": idempotency_key,
        },
        json=make_payload(),
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["message"]


@pytest.mark.asyncio
async def test_health_is_public(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readiness_reports_database_state(client: AsyncClient) -> None:
    async def database_ok() -> None:
        return None

    app = fastapi_app
    app.dependency_overrides[health_module.get_database_check] = lambda: database_ok
    try:
        ready = await client.get("/health/ready")
    finally:
        app.dependency_overrides.pop(health_module.get_database_check, None)

    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "database": "ok"}

    async def database_down() -> None:
        raise ConnectionError("database is down")

    app.dependency_overrides[health_module.get_database_check] = lambda: database_down
    try:
        not_ready = await client.get("/health/ready")
    finally:
        app.dependency_overrides.pop(health_module.get_database_check, None)

    assert not_ready.status_code == 503
    assert not_ready.json()["error"]["code"] == "not_ready"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/docs", "/openapi.json"])
async def test_docs_are_disabled_by_default(
    client: AsyncClient,
    path: str,
) -> None:
    response = await client.get(path)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
