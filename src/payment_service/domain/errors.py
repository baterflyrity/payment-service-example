from __future__ import annotations

from uuid import UUID


class DomainError(Exception):
    """Базовое исключение доменного слоя."""


class PaymentNotFound(DomainError):
    def __init__(self, payment_id: UUID) -> None:
        self.payment_id = payment_id
        super().__init__(f"Платёж {payment_id} не найден")


class IdempotencyConflict(DomainError):
    """Ключ идемпотентности уже использован с другими данными запроса."""

    def __init__(self, idempotency_key: str) -> None:
        self.idempotency_key = idempotency_key
        super().__init__(
            "Ключ идемпотентности уже использован с другим набором данных"
        )


class DuplicateIdempotencyKey(DomainError):
    """Гонка при вставке: ключ уже занят параллельной транзакцией."""

    def __init__(self, idempotency_key: str) -> None:
        self.idempotency_key = idempotency_key
        super().__init__(
            f"Ключ идемпотентности {idempotency_key!r} уже существует"
        )


class InvalidStatusTransition(DomainError):
    def __init__(self, current: str, target: str) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Недопустимый переход статуса: {current} -> {target}")
