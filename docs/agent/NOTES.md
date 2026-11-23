# Заметки вне scope

## T01
- `.env.example` начинается со строки `[TEMPLATE]` — похоже на случайно оставленный маркер. `docker compose` и pydantic-settings её принимают (проверено), но для чистого README/примера в T09 строку стоит убрать.
- `consumer` в compose ждёт healthy `api`, хотя для consumer'а достаточно БД и RabbitMQ. Осознанно не менялось в T01 (вне границ).
- Dockerfile копирует `alembic` и `alembic.ini`; после переезда ORM (T03) проверить, что `env.py` всё ещё импортирует актуальный metadata.
