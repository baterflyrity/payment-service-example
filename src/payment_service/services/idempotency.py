import hashlib
import json
from decimal import Decimal

from payment_service.schemas.payment import PaymentCreate


def calculate_request_hash(payload: PaymentCreate) -> str:
    normalized_payload = {
        "amount": format(payload.amount.quantize(Decimal("0.01")), "f"),
        "currency": payload.currency,
        "description": payload.description,
        "metadata": payload.metadata,
        "webhook_url": str(payload.webhook_url),
    }

    serialized = json.dumps(
        normalized_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )

    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
