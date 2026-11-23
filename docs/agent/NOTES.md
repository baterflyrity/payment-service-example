# Заметки вне scope

## T01
- `.env.example` начинается со строки `[TEMPLATE]` — похоже на случайно оставленный маркер. `docker compose` и pydantic-settings её принимают (проверено), но для чистого README/примера в T09 строку стоит убрать.
- `consumer` в compose ждёт healthy `api`, хотя для consumer'а достаточно БД и RabbitMQ. Осознанно не менялось в T01 (вне границ).
- Dockerfile копирует `alembic` и `alembic.ini`; после переезда ORM (T03) проверить, что `env.py` всё ещё импортирует актуальный metadata.

## T03
- `docker compose` интерполирует обязательный `API_KEY` для `api`/`consumer` даже при запуске только `postgres`; без `.env`/переменной команда падает. Для тестовых проверок использовался `API_KEY=test-api-key`. Возможно, стоит сделать `API_KEY` необязательным для инфраструктурных сервисов (T09).
- `alembic/versions/0001_initial.py` не проходит `ruff check alembic` по I001 (порядок импортов) — pre-existing, в границы T03 не входило. `ruff check src tests` зелёный.

## T04
- `schemas/` удалён не полностью: `schemas/events.py` (`PaymentCreatedEvent`) использует `workers/consumer.py`. Удаление/перенос этого модуля — в T06 (границы T04 запрещают трогать consumer). API-DTO теперь в `entrypoints/api/schemas.py`.
- `api/main.py` оставлен как шим `from payment_service.entrypoints.api.app import app`, потому что путь `payment_service.api.main:app` прописан в `Dockerfile` и `docker-compose.yml`. Перенести команды на `payment_service.entrypoints.api.app:app` — T05/T09.
- `OutboxORM.event_type` теперь `payment.created` (значение `PaymentCreated.event_type` из T02); старый роутер писал `payments.new`. Публикация и consumer читают только payload, но при анализе outbox стоит учитывать новое значение.
- В окружении нет `setfacl`, поэтому default ACL на каталоги не настроить: файлы, созданные контейнером от root с umask 022, нужно нормализовать (`chown user:root` + `chmod g+rw`) после запуска контейнера.
- `CreatePaymentService` делает два UoW на успешный запрос (поиск ключа, затем вставка) — как предписано ARCHITECTURE. При необходимости оптимизировать (один UoW с повторной сверкой) — отдельная задача.

## T05
- Exchange `payments` (direct) объявлен в `messaging/topology.py`, очередь `payments.new` привязывается к нему relay-процессом по routing key `payments.new`. Consumer (T06) должен подписываться на очередь через этот exchange и не переобъявлять её с другими аргументами.
- В compose у `consumer` остались неиспользуемые `OUTBOX_POLL_INTERVAL_SECONDS`/`OUTBOX_BATCH_SIZE`, а также зависимость от healthy `api` (см. T01). Вне границ T05 — чистить в T06/T09.
- Старый `tests/test_outbox_publisher.py` (прямые SQL-запросы) удалён вместе с `workers/outbox_publisher.py`. SQL-поведение `lock_unpublished`/`mark_published`/`mark_failed` покрыто `tests/integration/test_repositories.py`, сам relay — unit-тестами на fakes.
- `application/relay_outbox.py` восстанавливает `PaymentCreated` из payload outbox; payload обязан содержать `payment_id` и `occurred_at` в ISO-формате (так пишет `SqlAlchemyOutboxRepository.add`).
- `docker compose ps/config` по-прежнему требуют `API_KEY` (pre-existing, T03).

## T06
- В compose у `consumer` остались неиспользуемые `OUTBOX_POLL_INTERVAL_SECONDS`, `OUTBOX_BATCH_SIZE`, `API_KEY` и зависимость от healthy `api`. Команда consumer обновлена на `payment_service.entrypoints.consumer:app`; чистка env/depends_on — T09.
- Старые durable-очереди `payments.retry.2s`/`payments.retry.4s` из предыдущей реализации могут остаться в томе RabbitMQ; новый код использует `payments.retry.1`/`payments.retry.2`. На чистых окружениях не проявляется, но при обновлении существующего тома старые очереди стоит удалить вручную.
- `docker compose build` нового consumer в T06 не проверялся (в границы входил только код и тесты против реального RabbitMQ); сборка образа и e2e — T08/T09.

## T07
- Добавлен флаг `ENABLE_DOCS` (по умолчанию `false`, `/docs`, `/redoc`, `/openapi.json` отключены). Его нужно описать в `.env.example` и README (T09), вместе с эндпоинтами `/health` и `/health/ready` и форматом ошибок `{"error": {"code", "message"}}`.
- Для readiness-проверки в `infrastructure/db/session.py` добавлена функция `ping_database()`: держать импорт `sqlalchemy` в `entrypoints/api` нельзя (F2), поэтому проверка живёт в infrastructure, а API получает её через зависимость `get_database_check` (подменяется в тестах).
- `X-API-Key` теперь проверяется одинаково на всех эндпоинтах платежей; `/health` и `/health/ready` намеренно публичные.
- В compose healthcheck `api` переведён на `/health`; у `consumer` по-прежнему неиспользуемые env и зависимость от healthy `api` (см. T06) — T09.
- В тестах `/health/ready` проверяется через overrides зависимости, без реального подключения к БД; интеграционная проверка readiness на живой БД остаётся на T08/T09.
