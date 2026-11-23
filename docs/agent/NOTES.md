# Заметки вне scope

## T01
- `.env.example` начинается со строки `[TEMPLATE]` — похоже на случайно оставленный маркер. `docker compose` и pydantic-settings её принимают (проверено), но для чистого README/примера в T09 строку стоит убрать.
- `consumer` в compose ждёт healthy `api`, хотя для consumer'а достаточно БД и RabbitMQ. Осознанно не менялось в T01 (вне границ).
- Dockerfile копирует `alembic` и `alembic.ini`; после переезда ORM (T03) проверить, что `env.py` всё ещё импортирует актуальный metadata.

## T03
- `docker compose` интерполирует обязательный `API_KEY` для `api`/`consumer` даже при запуске только `postgres`; без `.env`/переменной команда падает. Для тестовых проверок использовался `API_KEY=test-api-key`. Возможно, стоит сделать `API_KEY` необязательным для инфраструктурных сервисов (T09).
- `alembic/versions/0001_initial.py` не проходит `ruff check alembic` по I001 (порядок импортов) — pre-existing, в границы T03 не входило. `ruff check src tests` зелёный.
