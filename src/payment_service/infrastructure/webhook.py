"""Отправка webhook-уведомлений через httpx с защитой от SSRF."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx

DEFAULT_WEBHOOK_TIMEOUT_SECONDS = 10.0

AddressResolver = Callable[[str, int], Awaitable[list[str]]]


class WebhookDestinationForbidden(Exception):
    """Адрес webhook отклонён SSRF-политикой; повторять запрос бессмысленно."""


def _is_forbidden_address(address: str) -> bool:
    """True, если адрес не должен получать webhook.

    Учитывает IPv4-mapped IPv6 (``::ffff:127.0.0.1``): проверяется и исходный
    IPv6-адрес, и вложенный IPv4.
    """

    candidates = [address]

    # IPv6 link-local адреса могут приходить со scope-id (``fe80::1%eth0``).
    normalized = address.split("%", 1)[0]

    try:
        parsed = ipaddress.ip_address(normalized)
    except ValueError:
        # Неразбираемый адрес считаем недоверенным.
        return True

    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        candidates.append(str(parsed.ipv4_mapped))

    for candidate in candidates:
        address_obj = ipaddress.ip_address(candidate)
        if (
            address_obj.is_loopback
            or address_obj.is_private
            or address_obj.is_link_local
            or address_obj.is_multicast
            or address_obj.is_reserved
            or address_obj.is_unspecified
        ):
            return True

    return False


async def _default_resolver(host: str, port: int) -> list[str]:
    """Резолвит хост в список IP-адресов через ``asyncio.getaddrinfo``."""

    infos = await asyncio.getaddrinfo(
        host,
        port,
        type=socket.SOCK_STREAM,
    )
    return sorted({info[4][0] for info in infos})


class HttpxWebhookSender:
    """Отправляет payload на webhook_url.

    Не-2xx ответ и сетевые ошибки пробрасываются как исключения, чтобы
    consumer повторил обработку. Адрес проверяется перед каждым запросом:
    резолвинг выполняется заново, поэтому DNS rebinding не обходит проверку.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        timeout_seconds: float = DEFAULT_WEBHOOK_TIMEOUT_SECONDS,
        allowed_hosts: frozenset[str] | set[str] | None = None,
        resolver: AddressResolver | None = None,
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds
        self._allowed_hosts = frozenset(
            host.strip().lower().rstrip(".") for host in (allowed_hosts or ())
        )
        self._resolver = resolver or _default_resolver

    async def ensure_destination_allowed(self, webhook_url: str) -> None:
        """Проверяет схему, host и все резолвящиеся адреса назначения."""

        parts = urlsplit(webhook_url)

        if parts.scheme.lower() not in {"http", "https"}:
            raise WebhookDestinationForbidden(
                f"unsupported webhook scheme: {parts.scheme!r}",
            )

        host = (parts.hostname or "").strip().lower().rstrip(".")

        if not host:
            raise WebhookDestinationForbidden("webhook URL has no host")

        if host in self._allowed_hosts:
            return

        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)

        try:
            addresses = await self._resolver(host, port)
        except OSError as exc:
            # Неразрешимый хост — обычная сетевая ошибка (retry), а не
            # запрещённый адрес.
            raise httpx.ConnectError(
                f"Cannot resolve webhook host {host!r}: {exc}",
            ) from exc

        if not addresses:
            raise WebhookDestinationForbidden(
                f"webhook host {host!r} resolved to no addresses",
            )

        forbidden = [address for address in addresses if _is_forbidden_address(address)]

        if forbidden:
            raise WebhookDestinationForbidden(
                f"webhook host {host!r} resolves to forbidden address(es): "
                f"{', '.join(sorted(forbidden))}",
            )

    async def send(
        self,
        webhook_url: str,
        payload: Mapping[str, Any],
    ) -> None:
        await self.ensure_destination_allowed(webhook_url)

        response = await self._client.post(
            webhook_url,
            json=dict(payload),
            timeout=self._timeout_seconds,
            # Редирект мог бы увести запрос на внутренний адрес в обход
            # проверки назначения.
            follow_redirects=False,
        )
        response.raise_for_status()
