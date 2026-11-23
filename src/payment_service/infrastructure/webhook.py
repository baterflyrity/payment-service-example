"""Отправка webhook-уведомлений через httpx."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

DEFAULT_WEBHOOK_TIMEOUT_SECONDS = 10.0


class HttpxWebhookSender:
    """Отправляет payload на webhook_url.

    Не-2xx ответ и сетевые ошибки пробрасываются как исключения, чтобы
    consumer повторил обработку.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        timeout_seconds: float = DEFAULT_WEBHOOK_TIMEOUT_SECONDS,
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def send(
        self,
        webhook_url: str,
        payload: Mapping[str, Any],
    ) -> None:
        response = await self._client.post(
            webhook_url,
            json=dict(payload),
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
