"""Проверка адреса webhook перед отправкой (SSRF на стороне consumer'а)."""

from collections.abc import Mapping
from typing import Any

import httpx
import pytest

from payment_service.infrastructure.webhook import (
    HttpxWebhookSender,
    WebhookDestinationForbidden,
)


class FakeResponse:
    def raise_for_status(self) -> None:
        return None


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs))
        return FakeResponse()


def make_resolver(addresses: list[str]):
    calls: list[tuple[str, int]] = []

    async def resolve(host: str, port: int) -> list[str]:
        calls.append((host, port))
        return addresses

    resolve.calls = calls  # type: ignore[attr-defined]
    return resolve


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "169.254.169.254",
        "::1",
        "::ffff:127.0.0.1",
        "192.168.1.10",
        "fe80::1",
    ],
)
@pytest.mark.asyncio
async def test_forbidden_addresses_are_rejected(address: str) -> None:
    client = RecordingClient()
    sender = HttpxWebhookSender(client, resolver=make_resolver([address]))

    with pytest.raises(WebhookDestinationForbidden):
        await sender.send(
            "https://merchant.example/webhook",
            {"payment_id": "1"},
        )

    assert client.calls == []


@pytest.mark.asyncio
async def test_public_address_is_sent_without_redirects() -> None:
    client = RecordingClient()
    resolver = make_resolver(["93.184.216.34"])
    sender = HttpxWebhookSender(client, resolver=resolver)

    await sender.send(
        "https://merchant.example/webhook",
        {"payment_id": "1"},
    )

    assert resolver.calls == [("merchant.example", 443)]  # type: ignore[attr-defined]
    assert len(client.calls) == 1

    url, kwargs = client.calls[0]
    assert url == "https://merchant.example/webhook"
    assert kwargs["json"] == {"payment_id": "1"}
    assert kwargs["follow_redirects"] is False


@pytest.mark.asyncio
async def test_single_forbidden_address_among_public_ones_rejects() -> None:
    client = RecordingClient()
    sender = HttpxWebhookSender(
        client,
        resolver=make_resolver(["93.184.216.34", "127.0.0.1"]),
    )

    with pytest.raises(WebhookDestinationForbidden):
        await sender.send("https://merchant.example/webhook", {})

    assert client.calls == []


@pytest.mark.asyncio
async def test_allowed_host_skips_address_checks() -> None:
    client = RecordingClient()
    resolver = make_resolver(["172.18.0.5"])
    sender = HttpxWebhookSender(
        client,
        allowed_hosts={"e2e-webhook-receiver"},
        resolver=resolver,
    )

    await sender.send("http://e2e-webhook-receiver:8000/webhook", {})

    assert resolver.calls == []  # type: ignore[attr-defined]
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_unresolvable_host_is_a_network_error() -> None:
    async def failing_resolver(host: str, port: int) -> list[str]:
        del host, port
        raise OSError("name resolution failed")

    client = RecordingClient()
    sender = HttpxWebhookSender(client, resolver=failing_resolver)

    # Не запрещённый адрес, а обычная сетевая ошибка → consumer сделает retry.
    with pytest.raises(httpx.ConnectError, match="Cannot resolve webhook host"):
        await sender.send("https://merchant.example/webhook", {})

    assert client.calls == []


@pytest.mark.asyncio
async def test_payload_mapping_is_converted_to_dict() -> None:
    client = RecordingClient()
    sender = HttpxWebhookSender(
        client,
        resolver=make_resolver(["93.184.216.34"]),
    )
    payload: Mapping[str, Any] = {"a": 1}

    await sender.send("https://merchant.example/webhook", payload)

    assert isinstance(client.calls[0][1]["json"], dict)
