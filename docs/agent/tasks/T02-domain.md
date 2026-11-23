# T02. Доменный слой (F3)

## Контекст
`docs/agent/ARCHITECTURE.md` (раздел domain), `src/payment_service/models/payment.py` (только как справочник полей), `src/payment_service/services/idempotency.py`.

## Сделать
Создать `src/payment_service/domain/`:
- `payment.py`: `PaymentStatus` (StrEnum), `Currency` (StrEnum), `Payment` (dataclass) с фабрикой `Payment.create(...)` (валидирует amount > 0, квантует до 2 знаков), методами `mark_succeeded(now)`, `mark_failed(now)` (только из `pending`, иначе `InvalidStatusTransition`), `is_final`, `ensure_same_request(request_hash)` (иначе `IdempotencyConflict`).
- `events.py`: `PaymentCreated(event_id, payment_id, occurred_at)`; `Payment.create` возвращает платёж и регистрирует событие (`payment.pull_events()`).
- `errors.py`: `DomainError` и наследники `PaymentNotFound`, `IdempotencyConflict`, `InvalidStatusTransition`, `DuplicateIdempotencyKey`.
- `ports.py`: `typing.Protocol` для `PaymentRepository` (`add`, `get`, `get_by_idempotency_key`, `get_for_update`), `OutboxRepository` (`add(event)`, `lock_unpublished(limit)`, `mark_published(ids)`, `mark_failed(id, error)`), `UnitOfWork` (async CM, `payments`, `outbox`, `commit`, `rollback`), `PaymentGateway`, `WebhookSender`, `EventPublisher`.

## Границы
Только новые файлы в `domain/`. Никаких импортов sqlalchemy/fastapi/pydantic/faststream/httpx. Существующий код не трогать.

## Критерии готовности
- `tests/unit/domain/test_payment.py`: создание, валидация, переходы статусов (вкл. запрещённые), сверка idempotency, события.
- `uv run pytest tests/unit/domain -q` и `uv run ruff check src tests` зелёные.
