# Целевая архитектура

Текущий код (точка старта): `src/payment_service/{api,models,schemas,services,workers,messaging}` — плоский, без слоёв. Переводим в:

```text
src/payment_service/
├── domain/                 # чистый Python, без внешних зависимостей
│   ├── payment.py          # Payment (dataclass), PaymentStatus, Currency, Money; методы mark_succeeded/mark_failed, matches_request(hash)
│   ├── events.py           # PaymentCreated (доменное событие)
│   ├── errors.py           # PaymentNotFound, IdempotencyConflict, InvalidStatusTransition
│   └── ports.py            # Protocol: PaymentRepository, OutboxRepository, UnitOfWork, PaymentGateway, WebhookSender, EventPublisher
├── application/            # use cases; знает только domain + ports
│   ├── commands.py         # CreatePaymentCommand (dataclass)
│   ├── create_payment.py   # идемпотентность + запись outbox в одном UoW
│   ├── get_payment.py
│   ├── process_payment.py  # обработка события consumer'ом
│   ├── relay_outbox.py     # выборка/публикация/пометка outbox
│   └── idempotency.py      # канонический хеш запроса
├── infrastructure/
│   ├── db/
│   │   ├── orm.py          # SQLAlchemy-модели (PaymentORM, OutboxORM) — только маппинг
│   │   ├── mappers.py      # ORM <-> domain
│   │   ├── repositories.py # SqlAlchemyPaymentRepository, SqlAlchemyOutboxRepository
│   │   ├── uow.py          # SqlAlchemyUnitOfWork (async context manager, commit/rollback)
│   │   └── session.py      # engine, session factory
│   ├── messaging/          # topology (exchanges/queues), FastStream publisher
│   ├── gateway.py          # эмулятор шлюза
│   └── webhook.py          # httpx-отправка
├── entrypoints/
│   ├── api/                # FastAPI: app, routers, schemas (Pydantic DTO), deps, error handlers
│   ├── consumer.py         # FastStream app → application.process_payment
│   └── outbox_relay.py     # цикл relay → application.relay_outbox
├── config.py
└── container.py            # сборка зависимостей (фабрики UoW/сервисов)
alembic/                    # env.py + versions/0001_initial.py — КОММИТИТСЯ
```

Правила зависимостей: `entrypoints → application → domain ← infrastructure`. Pydantic только в `entrypoints` (DTO) и `config`.

## Ключевые решения
- **Идемпотентность**: `CreatePayment` в одном UoW: `payments.get_by_idempotency_key` → если есть, сверка хеша (домен) → вернуть/409; иначе `add` + `outbox.add(PaymentCreated)` → commit. На `IntegrityError` по уникальному ключу (гонка) репозиторий бросает доменное `DuplicateIdempotencyKey`, сервис перечитывает в новом UoW и повторяет сверку.
- **Outbox relay**: отдельный процесс/сервис compose. `outbox.lock_unpublished(batch)` (`FOR UPDATE SKIP LOCKED`) → publish → `mark_published` в том же UoW. At-least-once; `event_id` в сообщении.
- **Consumer**: идемпотентен — если платёж уже в финальном статусе, шлюз не вызывается, только повтор webhook. Статус сохраняется до webhook.
- **Retry/DLQ**: exchange `payments` (direct) → `payments.new`; ошибка → публикация в `payments.retry` с заголовком `x-attempt` в очередь с TTL (2 с, 4 с) и DLX обратно в `payments`; после 3-й попытки → exchange `payments.dlx` → `payments.dlq`.
