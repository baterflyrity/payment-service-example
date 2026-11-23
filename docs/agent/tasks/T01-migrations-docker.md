# T01. Миграции Alembic в репозитории и рабочая Docker-сборка (F1)

## Контекст (читать только это)
`.gitignore`, `.dockerignore`, `Dockerfile`, `docker-compose.yml`, `alembic.ini`, `.env.example`, `src/payment_service/models/*.py`, `src/payment_service/db.py`, `src/payment_service/config.py`.

## Сделать
1. Убрать `/alembic/` из `.gitignore`; проверить, что `.dockerignore` не исключает `alembic/`.
2. Создать `alembic/env.py` (async, URL из `config`, `target_metadata` = metadata ORM) и `alembic/script.py.mako`.
3. Написать **вручную** `alembic/versions/0001_initial.py`: таблицы `payments` и `outbox` со всеми колонками, CHECK-ограничениями, уникальным `idempotency_key`, индексами — как в текущих моделях. `downgrade` удаляет таблицы.
4. Миграции применяет отдельный одноразовый сервис compose `migrations` (`alembic upgrade head`); `api`, `consumer` зависят от него через `condition: service_completed_successfully`.
5. Сверить `.env.example` с compose: все переменные присутствуют, `docker compose config` проходит без ошибок.

## Границы
Не менять бизнес-логику и структуру пакетов (это T02–T06). Если пути к metadata позже изменятся — T03 обновит `env.py`.

## Критерии готовности
- `git ls-files alembic` показывает `env.py` и `versions/0001_initial.py`.
- `docker compose build` успешен; `docker compose up -d` → `migrations` завершился с кодом 0, в БД есть `payments`, `outbox`, `alembic_version`.
- `alembic downgrade base && alembic upgrade head` проходит.
- Если Docker недоступен в среде — проверить миграции на локальном PostgreSQL и явно написать в коммите, что сборка образа не проверена.
