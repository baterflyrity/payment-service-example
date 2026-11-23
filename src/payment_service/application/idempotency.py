import hashlib
import json
from decimal import Decimal

from payment_service.application.commands import CreatePaymentCommand


def calculate_request_hash(command: CreatePaymentCommand) -> str:
    """Канонический хеш значимых полей запроса.

    Хеш считается по command, а не по Pydantic-схеме, чтобы application
    не зависел от транспорта. Порядок ключей и эквивалентность 10.0/10.00
    нормализуются.
    """

    normalized_payload = {
        "amount": format(command.amount.quantize(Decimal("0.01")), "f"),
        "currency": str(command.currency),
        "description": command.description,
        "metadata": command.metadata,
        "webhook_url": command.webhook_url,
    }

    serialized = json.dumps(
        normalized_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )

    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
