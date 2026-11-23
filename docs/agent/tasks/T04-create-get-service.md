# T04. Use cases CreatePayment / GetPayment, тонкий роутер (F2, F4)

## Контекст
`docs/agent/ARCHITECTURE.md` (раздел «Ключевые решения → Идемпотентность»), `domain/*`, `infrastructure/db/uow.py`, `src/payment_service/api/payments.py`, `src/payment_service/schemas/payment.py`, `src/payment_service/services/idempotency.py`, `tests/test_payments_api.py`.

## Сделать
1. `application/idempotency.py` — перенос хеша запроса (работает с `CreatePaymentCommand`, не с Pydantic).
2. `application/create_payment.py`: `CreatePaymentService(uow_factory, clock)`. Алгоритм из ARCHITECTURE: поиск по ключу → `ensure_same_request` → вернуть существующий; иначе `Payment.create` + `outbox.add` для каждого события + `commit`. На `DuplicateIdempotencyKey` — один повтор в новом UoW. Возвращает `(payment, created: bool)`.
3. `application/get_payment.py`: бросает `PaymentNotFound`.
4. `entrypoints/api/`: Pydantic DTO, роутер (≤ ~10 строк на эндпоинт: DTO → command → сервис → DTO), DI через `Depends` из `container.py`, глобальные exception handlers: `IdempotencyConflict→409`, `PaymentNotFound→404`, `DomainError→422`.
5. Удалить старые `api/payments.py`, `schemas/`, `services/idempotency.py`.

## Границы
Не трогать consumer и outbox relay.

## Критерии готовности
- В `entrypoints/api` нет импортов `sqlalchemy`.
- Unit-тесты сервиса на in-memory fake UoW: новый платёж + 1 outbox-событие; повтор → тот же id, событий не добавлено; другой body → `IdempotencyConflict`; гонка (fake бросает `DuplicateIdempotencyKey`) → возвращается существующий.
- Интеграционный тест: 10 параллельных POST с одним ключом → 1 строка payments, 1 строка outbox.
- API-тесты адаптированы и зелёные.
