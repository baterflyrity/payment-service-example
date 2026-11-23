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
