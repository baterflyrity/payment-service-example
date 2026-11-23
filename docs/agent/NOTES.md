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

## T09
- Чистая проверка выполнена из свежего клона `/tmp/fresh` (клон локального репозитория + staged-патч T09, т.к. коммит делается после проверки): `cp .env.example .env && docker compose up --build -d`.
- `docker compose ps -a` (фрагмент, все сервисы в ожидаемом состоянии):

  ```text
  NAME                   IMAGE                          SERVICE        STATUS
  fresh-api-1            fresh-api                      api            Up (healthy)   127.0.0.1:8000->8000/tcp
  fresh-consumer-1       fresh-consumer                 consumer       Up
  fresh-migrations-1     fresh-migrations               migrations     Exited (0)
  fresh-outbox-relay-1   fresh-outbox-relay             outbox-relay   Up
  fresh-postgres-1       postgres:17-alpine             postgres       Up (healthy)
  fresh-rabbitmq-1       rabbitmq:4-management-alpine   rabbitmq       Up (healthy)
  ```

- `/health` → `200`, `/health/ready` → `{"status":"ready","database":"ok"}`.
- curl-сценарий из README: POST → `202 {"payment_id":"9817a779-6ca0-4c53-a4f1-1e40c93bab6d","status":"pending",...}`; GET через ~7 с →

  ```json
  {"payment_id":"9817a779-6ca0-4c53-a4f1-1e40c93bab6d","amount":"125.50","currency":"RUB","description":"Clean clone smoke","metadata":{"order_id":"123"},"status":"succeeded","webhook_url":"https://merchant.example/webhooks/payments","created_at":"2026-11-23T20:55:45.854605Z","processed_at":"2026-11-23T20:55:51.086987Z"}
  ```

- E2E-тест против этого же стека: `E2E_API_KEY=... pytest -m e2e -q` → `1 passed`. После проверки: `docker compose down -v`.
- Устранены отложенные в предыдущих задачах пункты: строка `[TEMPLATE]` в `.env.example`, неиспользуемые `API_KEY`/`OUTBOX_*` и `depends_on: api` у `consumer`, команды `api` переведены на `payment_service.entrypoints.api.app:app` (compose и Dockerfile). Шим `api/main.py` оставлен для обратной совместимости.
- Осталось: `docker compose ps/logs/down` без `.env`/`API_KEY` падают из-за `${API_KEY:?...}` — это осознанно (README требует `cp .env.example .env`).

## T08
- Тесты разделены: `tests/unit` (без БД), `tests/integration` (PostgreSQL; фикстуры в `tests/integration/conftest.py`), `tests/e2e` (поднятый compose). Маркеры `integration`, `rabbit`, `e2e` объявлены в `pyproject.toml`.
- E2E-тест (`tests/e2e/test_flow.py`) требует уже запущенный стек и `API_KEY`, совпадающий с `E2E_API_KEY` (или `API_KEY`); при отсутствии docker/сервиса `consumer` он пропускается. Для README (T09): команды `docker compose up -d --build`, `E2E_API_KEY=... pytest -m e2e -q`, а также `RABBITMQ_URL=amqp://payments:payments@127.0.0.1:25672/ pytest -m rabbit`.
- Pre-existing: `docker compose ps/logs/stop` и `config` падают без переменной `API_KEY` из-за `${API_KEY:?...}` — при работе с инфраструктурой задавать `API_KEY=...`. Чистка env/`depends_on` у `consumer` остаётся на T09.
- `ruff format --check` расходится с текущим кодом в части существующих файлов; проект использует `ruff check`, форматирование в DoD не входило.

## T09 (закрытые пункты)
- `.env.example` очищен от `[TEMPLATE]`, добавлен `ENABLE_DOCS=false`.
- `consumer` больше не зависит от healthy `api` и не получает неиспользуемые `API_KEY`/`OUTBOX_*`.
- README описывает актуальные слои, `outbox-relay`, три exchange'а, health/readiness, формат ошибок, `ENABLE_DOCS` и команды всех уровней тестов.

## T11
- `alembic downgrade base` на БД, где перед этим отработали интеграционные тесты,
  падает с `index "ix_outbox_published_created_at" does not exist`: `Base.metadata.drop_all`
  удаляет таблицы, но не `alembic_version`, и Alembic считает схему применённой.
  Миграции нужно проверять на свежесозданной БД (или отдельной схеме); на чистой БД
  цикл upgrade → downgrade → upgrade проходит. Автотеста на соответствие ORM и
  миграций по-прежнему нет.
- `asyncio.getaddrinfo` не существует: это метод event loop. Первый e2e-прогон после
  включения SSRF-проверки упал с `AttributeError`; исправлено на
  `loop.getaddrinfo`. Unit-тесты с подменённым резолвером этого не ловили — добавлен
  тест на реальный резолвинг `localhost`.
- E2E-приёмник webhook запускается тем же образом и теперь работает от UID 10001;
  каталог `tmpfs`/bind-mount должен быть доступен ему на запись (`chmod 0o777` в тесте).
- `WEBHOOK_ALLOW_HTTP` нужен не только consumer'у, но и `api`: входная валидация
  `webhook_url` выполняется в API-процессе. Прокинут в оба сервиса.
- `Settings` теперь требует `API_KEY`, поэтому его получают все сервисы, включая
  `migrations` (alembic env импортирует `settings`) и `outbox-relay`.
- `WEBHOOK_ALLOWED_HOSTS` обходит проверку адресов для доверенных имён; список
  по умолчанию пуст. Для e2e имя приёмника фиксировано (`e2e-webhook-receiver`).
- Между DNS-резолвингом и подключением остаётся TOCTOU (httpx резолвит имя ещё раз).
  Устранение требует подключения по проверенному IP с сохранением Host/SNI — вне T11.
- Смена `POSTGRES_PASSWORD`/`RABBITMQ_DEFAULT_PASS` не применяется к уже
  инициализированному тому PostgreSQL: после смены нужен `docker compose down -v`.
  Проверяющим, которые меняют пароли после первого запуска, стоит об этом знать.
- В `.env.example` была строка `[TEMPLATE]` (см. T01); при переписывании шаблона в T11
  она удалена.
- `ruff format --check` по-прежнему расходится с существующим кодом (pre-existing).

## T10
- `Idempotency-Key` из одних пробелов HTTP-парсер нормализует в пустую строку, поэтому FastAPI сообщает `header.Idempotency-Key: Field required` (всё ещё `422` + `validation_error`). Если нужен текст «must not be empty», понадобится собственный `Header`-валидатор, а не зависимость.
- `ruff format --check` расходится с существующим кодом (pre-existing): проект проверяет только `ruff check`, форматирование в DoD не входит. Если вводить формат-проверку — отдельная задача с прогоном по всему репозиторию.
- Интеграционные тесты создают схему через `Base.metadata.create_all`, а не через Alembic. Миграции проверены отдельно (`alembic downgrade base && alembic upgrade head` на `payments_test`), но автотеста на соответствие ORM и миграций нет — кандидат на отдельную задачу.
- Ручной curl из README с `webhook_url=https://merchant.example/...` даёт ожидаемые `httpx.ConnectError` и retry→DLQ (хост не резолвится). Статус платежа при этом фиксируется до webhook. Для проверки успешной доставки webhook использовать e2e-тест, а не ручной curl.
- Основной compose-проект после интеграционных проверок остановлен (`docker compose stop`), тома сохранены; в чистом клоне выполнен `docker compose down -v`.
