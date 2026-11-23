# Спецификация: асинхронный сервис процессинга платежей

Источник: тестовое задание Senior Python (ниже — нормализованные требования) + обратная связь по прошлой сдаче.

## 1. Функциональные требования (из ТЗ)

### Payment
| Поле | Тип / правило |
|---|---|
| id | UUID |
| amount | Decimal, > 0, 2 знака |
| currency | RUB \| USD \| EUR |
| description | str (≤ 500) |
| metadata | JSON-объект |
| status | pending \| succeeded \| failed |
| idempotency_key | str, уникален (ограничение БД) |
| webhook_url | URL |
| created_at, processed_at | timestamptz; processed_at nullable |

### API (все эндпоинты — заголовок `X-API-Key`, статический ключ)
- `POST /api/v1/payments` — заголовок `Idempotency-Key` обязателен; body: amount, currency, description, metadata, webhook_url → `202 {payment_id, status, created_at}`.
- `GET /api/v1/payments/{payment_id}` → `200` детальная информация, `404` если нет.
- Ошибки: 401 (ключ), 404, 409 (тот же Idempotency-Key, другие данные), 422.

### Брокер / consumer
- При создании платежа событие публикуется в очередь `payments.new` **через Outbox**.
- Один consumer: получает событие → эмулирует шлюз (2–5 с, 90% succeeded / 10% failed) → обновляет статус в БД → шлёт webhook → retry при ошибках.
- Retry: 3 попытки с экспоненциальной задержкой; после 3-й неудачи — DLQ.
- Явно объявленные exchanges (не только default exchange): основной, retry, DLX.

### Инфраструктура
- Стек: FastAPI + Pydantic v2, SQLAlchemy 2.0 async, PostgreSQL, RabbitMQ (FastStream), Alembic, Docker + compose.
- Миграции: таблицы `payments` и `outbox`.
- compose: postgres, rabbitmq, api, consumer (+ допустимо отдельный `outbox-relay`).
- README: запуск и примеры.

## 2. Требования из обратной связи (обязательные, блокирующие)

| # | Замечание | Требование |
|---|---|---|
| F1 | `alembic/` в `.gitignore`, Docker не собирается | Миграции закоммичены; `git clone` + `cp .env.example .env` + `docker compose up --build` работает на чистой машине. Проверяется в T01 и T09. |
| F2 | SQLAlchemy-запросы в роутерах/сервисах/outbox | Весь доступ к БД — только через репозитории; транзакции — только через Unit of Work. `AsyncSession` и `sqlalchemy` **не импортируются** вне `infrastructure/`. |
| F3 | ORM-модели = бизнес-сущности | Отдельный доменный слой: чистые dataclass-сущности без зависимостей от SQLAlchemy/FastAPI/Pydantic; бизнес-правила (переходы статусов, сверка idempotency) — в домене. ORM-модели — только маппинг в `infrastructure/db`. |
| F4 | Идемпотентность и outbox в роутере | Роутер: только парсинг запроса → вызов сервиса → маппинг результата/ошибки в HTTP. Идемпотентность и создание outbox-события — в application-сервисе. |
| F5 | «Работало и обеспечивало гарантии» | Гарантии подтверждены тестами: атомарность payment+outbox, гонка одинаковых Idempotency-Key, at-least-once публикация, идемпотентный consumer, retry→DLQ. |

## 3. Проверяемые инварианты (архитектурные тесты в T08)
- `domain/` не импортирует `sqlalchemy`, `fastapi`, `pydantic`, `faststream`, `httpx`.
- `api/` и `application/` не импортируют `sqlalchemy`.
- `.gitignore` не содержит `alembic`.
