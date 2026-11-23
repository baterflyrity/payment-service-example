# T03. ORM-маппинг, репозитории, Unit of Work (F2, F3)

## Контекст
`docs/agent/ARCHITECTURE.md`, `src/payment_service/domain/ports.py`, `src/payment_service/domain/payment.py`, `src/payment_service/models/*.py`, `src/payment_service/db.py`, `alembic/env.py`, `tests/conftest.py`.

## Сделать
1. Перенести ORM-модели в `infrastructure/db/orm.py` (`PaymentORM`, `OutboxORM`), engine/session-factory в `infrastructure/db/session.py`. Схема БД **не меняется** (миграция 0001 остаётся валидной; проверить `alembic check` / autogenerate пуст).
2. `mappers.py`: ORM ↔ domain.
3. `repositories.py`: реализации портов. `add` для payment ловит `IntegrityError` по `uq` idempotency_key и бросает `DuplicateIdempotencyKey`. `lock_unpublished` — `SELECT ... FOR UPDATE SKIP LOCKED ORDER BY created_at LIMIT n`. `get_for_update` — `FOR UPDATE`.
4. `uow.py`: `SqlAlchemyUnitOfWork(session_factory)`; `__aenter__` открывает сессию и транзакцию, `__aexit__` делает rollback при исключении/без commit; репозитории — атрибуты UoW.
5. Обновить `alembic/env.py` на новый путь metadata. Старые `models/`, `db.py` удалить, импорты поправить минимально (код в роутере/воркерах пока может временно использовать `session_factory` — его перепишут T04–T06).

## Границы
Не переписывать роутер, consumer, outbox publisher (только импорты).

## Критерии готовности
- Интеграционные тесты `tests/integration/test_repositories.py` на тестовой БД (`*_test`): add/get, дубликат ключа → `DuplicateIdempotencyKey`, rollback UoW без commit, `SKIP LOCKED` (две параллельные UoW не получают одно событие).
- `uv run pytest -q`, `ruff` зелёные.
