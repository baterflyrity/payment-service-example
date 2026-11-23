from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from payment_service.domain.payment import Currency


@dataclass(frozen=True, slots=True)
class CreatePaymentCommand:
    """Входные данные use case создания платежа."""

    amount: Decimal
    currency: Currency
    description: str
    webhook_url: str
    idempotency_key: str
    metadata: dict[str, Any] = field(default_factory=dict)
