# T09. README и финальная проверка с чистого клона (F1, F5)

## Контекст
`README.md`, `docs/agent/SPEC.md`, `docs/agent/ARCHITECTURE.md`, `docker-compose.yml`, `.env.example`.

## Сделать
1. README: обновить структуру проекта и диаграммы (слои, `outbox-relay`, exchanges), запуск, примеры curl, тесты, раздел «Архитектурные решения» (почему UoW/репозитории/домен), ограничения. Удалить упоминания несуществующего.
2. Финальная проверка в **новой** директории: `git clone <локальный путь> /tmp/fresh && cd /tmp/fresh && cp .env.example .env && docker compose up --build -d` → все сервисы healthy/exited 0 → curl-сценарий из README даёт `succeeded|failed` → `docker compose down -v`.
3. `git status` чистый; в `.gitignore` нет путей, нужных сборке (`alembic`, `.env.example`).

## Критерии готовности
Результаты шага 2 (вывод `docker compose ps` и ответ GET) записаны в `docs/agent/NOTES.md`. Если Docker недоступен — явно указать это, не заявлять успех.
