from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PaymentCreated:
    """Событие о создании платежа."""

    event_id: UUID
    payment_id: UUID
    occurred_at: datetime

    @property
    def event_type(self) -> str:
        return "payment.created"


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    """Запись outbox, подготовленная репозиторием к публикации."""

    id: UUID
    event_id: UUID
    event_type: str
    payload: dict[str, Any]
    attempts: int = 0
