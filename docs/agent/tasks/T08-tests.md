# T08. Добивка тестов и архитектурные проверки (F5)

## Контекст
`docs/agent/SPEC.md` (разделы 2–3), `tests/`, `pyproject.toml`.

## Сделать
1. Структура `tests/unit`, `tests/integration`, `tests/e2e`; маркеры в `pyproject.toml`.
2. `tests/unit/test_architecture.py`: AST-проверка импортов по инвариантам из SPEC §3.
3. Integration: атомарность (ошибка после `outbox.add` до commit → нет ни платежа, ни события).
4. `tests/e2e/test_flow.py` (маркер `e2e`, против поднятого compose): POST → ожидание `succeeded|failed` через GET → получение webhook локальным HTTP-сервером в отдельном контейнере/процессе.
5. Удалить устаревшие тесты, дублирующие новые.

## Критерии готовности
`uv run pytest -m "not e2e" -q` зелёный; покрытие `domain` + `application` ≥ 90%.
