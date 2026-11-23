# T05. Outbox relay через UoW как отдельный процесс (F2, F5)

## Контекст
`docs/agent/ARCHITECTURE.md`, `domain/ports.py`, `infrastructure/db/uow.py`, `src/payment_service/workers/outbox_publisher.py`, `src/payment_service/messaging/topology.py`, `src/payment_service/api/main.py`, `docker-compose.yml`, `tests/test_outbox_publisher.py`.

## Сделать
1. `application/relay_outbox.py`: `RelayOutboxService(uow_factory, publisher, batch_size)`; `run_once()` → в одном UoW `lock_unpublished` → publish каждого → `mark_published` успешных, `mark_failed` (attempts+1, last_error) при ошибке → commit. Возвращает число опубликованных.
2. `infrastructure/messaging/publisher.py`: `FastStreamEventPublisher` (publish в exchange `payments`, routing key `payments.new`, `message_id=event_id`, persistent, publisher confirms).
3. `entrypoints/outbox_relay.py`: цикл с `poll_interval`, graceful shutdown по SIGTERM.
4. Убрать запуск publisher из lifespan API; добавить сервис `outbox-relay` в compose.

## Границы
Topology exchanges/очередей может быть объявлена здесь минимально; полную retry/DLQ-топологию делает T06.

## Критерии готовности
- Unit-тесты на fake: успех → published; ошибка брокера → не published, attempts+1, повтор в следующем `run_once`.
- Нет `sqlalchemy` в `application/`.
- `pytest`, `ruff` зелёные.
