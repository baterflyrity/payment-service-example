import ipaddress
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
)

from payment_service.config import settings

Currency = Literal["RUB", "USD", "EUR"]
PaymentStatus = Literal["pending", "succeeded", "failed"]

# Ограничения на metadata: не более 16 КБ сериализованного JSON и не более
# 5 уровней вложенности. Защищает от «тяжёлых» и глубоко вложенных payload.
MAX_METADATA_BYTES = 16 * 1024
MAX_METADATA_DEPTH = 5


def json_depth(value: Any) -> int:
    """Глубина вложенности JSON-значения (объект верхнего уровня — 1)."""

    if isinstance(value, dict):
        return 1 + max((json_depth(item) for item in value.values()), default=0)

    if isinstance(value, list):
        return 1 + max((json_depth(item) for item in value), default=0)

    return 0


def validate_webhook_url(url: HttpUrl) -> HttpUrl:
    """Запрещает опасные для SSRF адреса webhook.

    Разрешён только ``https``; ``http`` — лишь при ``WEBHOOK_ALLOW_HTTP=true``.
    IP-литералы, ``localhost``/``*.localhost`` и URL с userinfo отклоняются.
    """

    scheme = url.scheme.lower()

    if scheme != "https" and not (
        scheme == "http" and settings.webhook_allow_http
    ):
        raise ValueError(
            "webhook_url must use https "
            "(http is allowed only when WEBHOOK_ALLOW_HTTP=true)",
        )

    if url.username or url.password:
        raise ValueError("webhook_url must not contain user information")

    host = (url.host or "").strip().lower().rstrip(".")

    if not host:
        raise ValueError("webhook_url must contain a host")

    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("webhook_url must not point to localhost")

    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        raise ValueError("webhook_url must not use an IP address literal")

    return url


class PaymentCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    amount: Decimal = Field(
        gt=0,
        max_digits=18,
        decimal_places=2,
    )
    currency: Currency
    description: str = Field(
        min_length=1,
        max_length=500,
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    webhook_url: HttpUrl

    @field_validator("metadata")
    @classmethod
    def _metadata_is_json_safe_and_bounded(
        cls,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must contain valid JSON values") from exc

        if len(serialized.encode("utf-8")) > MAX_METADATA_BYTES:
            raise ValueError(
                f"metadata must be at most {MAX_METADATA_BYTES} bytes as JSON",
            )

        if json_depth(value) > MAX_METADATA_DEPTH:
            raise ValueError(
                f"metadata must be nested at most {MAX_METADATA_DEPTH} levels deep",
            )

        return value

    @field_validator("webhook_url")
    @classmethod
    def _webhook_url_is_safe(cls, value: HttpUrl) -> HttpUrl:
        return validate_webhook_url(value)


class PaymentCreated(BaseModel):
    payment_id: UUID
    status: PaymentStatus
    created_at: datetime


class PaymentDetail(BaseModel):
    payment_id: UUID
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, Any]
    status: PaymentStatus
    webhook_url: HttpUrl
    created_at: datetime
    processed_at: datetime | None
