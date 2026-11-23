# T07. Аутентификация, health, единый формат ошибок

## Контекст
`entrypoints/api/*`, `config.py`, `docker-compose.yml`.

## Сделать
1. ТЗ: X-API-Key «для всех эндпоинтов» — повесить на роутер платежей; `/docs` и `/openapi.json` закрыть ключом или отключить (`docs_url` по флагу `ENABLE_DOCS`), задокументировать выбор. Сравнение ключа — `secrets.compare_digest`.
2. `GET /health` (без ключа, liveness: обоснование в README) и `/health/ready` (проверка БД). Healthcheck compose перевести на `/health`.
3. Единый JSON ошибок `{"error": {"code", "message"}}` для доменных ошибок и 401.

## Критерии готовности
API-тесты: 401 без ключа/с неверным ключом на каждом эндпоинте, 404, 409, 422, health 200.
