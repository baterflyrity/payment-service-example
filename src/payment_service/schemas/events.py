from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PaymentCreatedEvent(BaseModel):
    """Event emitted by the transactional outbox."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    payment_id: UUID
