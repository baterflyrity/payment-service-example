# Payment Service Example

Асинхронный микросервис приёма и обработки платежей. Проект демонстрирует REST API на FastAPI, хранение состояния в PostgreSQL, надёжную публикацию событий через **Transactional Outbox**, обработку сообщений в RabbitMQ и уведомление клиента через webhook.

## Возможности

- Создание платежа и получение его статуса через REST API.
- Аутентификация статическим API-ключом в `X-API-Key`.
- Идемпотентность запросов по `Idempotency-Key` с проверкой идентичности данных.
- Асинхронное хранение событий в Outbox в одной транзакции с платежом.
- Отдельный процесс `outbox-relay` публикует события в RabbitMQ; неопубликованные события переотправляются после сбоя брокера.
- Consumer на FastStream: имитация платёжного шлюза (2–5 секунд; 90% `succeeded`, 10% `failed`), повтор обработки после технических ошибок, DLQ.
- Webhook с результатом обработки платежа.
- Миграции Alembic и контейнерный запуск через Docker Compose.
- Unit-, интеграционные, e2e- и архитектурные тесты.

## Архитектура

### Слои

```text
entrypoints → application → domain ← infrastructure
```

- `domain/` — чистые dataclass-сущности, value objects, доменные события, ошибки и порты (Protocol). Не зависит от SQLAlchemy, FastAPI, Pydantic, FastStream и httpx.
- `application/` — use case'ы (создание, чтение, обработка платежа, relay outbox). Знает только домен и порты.
- `infrastructure/` — SQLAlchemy-маппинг и репозитории, Unit of Work, RabbitMQ-публикатор и топология, эмулятор шлюза, отправка webhook.
- `entrypoints/` — FastAPI-приложение, consumer и процесс relay; Pydantic DTO живут только здесь.

Доступ к БД идёт только через репозитории, транзакции — только через Unit of Work. `AsyncSession`/`sqlalchemy` не импортируются вне `infrastructure/`; это проверяется архитектурным тестом.

### Компоненты и связи

```mermaid
flowchart LR
    Client[Клиент] -->|HTTP + API key| API[FastAPI API]
    API -->|Одна транзакция: payments + outbox| DB[(PostgreSQL)]
    Relay[outbox-relay] -->|FOR UPDATE SKIP LOCKED, затем публикация и published_at| DB
    Relay -->|exchange payments, RK payments.new| Rabbit[(RabbitMQ)]
    Rabbit -->|очередь payments.new| Consumer[FastStream consumer]
    Consumer -->|Чтение и обновление статуса| DB
    Consumer -->|HTTP POST с результатом| Webhook[Webhook клиента]
    Consumer -->|Техническая ошибка| Retry[payments.retry.1 / .2<br/>TTL 2 с / 4 с]
    Retry -->|DLX payments| Rabbit
    Consumer -->|Третья неудачная попытка| DLQ[(exchange payments.dlx → payments.dlq)]
```

### Создание и обработка платежа

```mermaid
sequenceDiagram
    autonumber
    participant C as Клиент
    participant A as FastAPI
    participant P as PostgreSQL
    participant O as outbox-relay
    participant R as RabbitMQ
    participant W as Consumer
    participant H as Webhook клиента

    C->>A: POST /api/v1/payments
    A->>P: BEGIN: INSERT payments + INSERT outbox, COMMIT
    A-->>C: 202 Accepted, payment_id, pending
    loop Периодический опрос
        O->>P: SELECT неопубликованных событий FOR UPDATE SKIP LOCKED
        O->>R: publish в exchange payments (RK payments.new)
        O->>P: COMMIT: published_at
    end
    R->>W: Событие из очереди payments.new
    W->>P: Прочитать платёж (FOR UPDATE)
    W->>W: Эмулировать шлюз (2–5 секунд)
    W->>P: Сохранить succeeded или failed
    W->>H: POST webhook с результатом
    H-->>W: HTTP 2xx
```

### Retry и Dead Letter Queue

```mermaid
flowchart TD
    Q[payments.new] --> C[Consumer: попытка обработки]
    C -->|Успех и webhook 2xx| ACK[Сообщение подтверждено]
    C -->|Ошибка, попытка 1| R2[payments.retry.1<br/>TTL = 2 секунды]
    R2 -->|После TTL через DLX в exchange payments| Q
    C -->|Ошибка, попытка 2| R4[payments.retry.2<br/>TTL = 4 секунды]
    R4 -->|После TTL через DLX в exchange payments| Q
    C -->|Ошибка, попытка 3| DLQ[(exchange payments.dlx → payments.dlq)]
```

Все exchange'и объявлены явно: `payments` (direct, события), `payments.retry` (direct, TTL-очереди с dead-letter в `payments`) и `payments.dlx` (direct, DLQ). Default exchange не используется.

## Технологии

- Python 3.14
- FastAPI, Pydantic v2
- SQLAlchemy 2.0 async, asyncpg, PostgreSQL
- RabbitMQ, FastStream
- Alembic
- Docker, Docker Compose
- pytest, pytest-asyncio, HTTPX, Ruff

## Быстрый запуск через Docker Compose

Требуются Docker Desktop (или Docker Engine с Compose plugin) и Git.

1. Клонируйте репозиторий:

   ```bash
   git clone https://github.com/baterflyrity/payment-service-example.git
   cd payment-service-example
   ```

2. Создайте локальный файл окружения:

   ```bash
   cp .env.example .env
   ```

   В Windows PowerShell используйте `Copy-Item .env.example .env`. Установите собственный `API_KEY` и замените тестовые пароли PostgreSQL и RabbitMQ. Файл `.env` не следует коммитить. Без `.env` команды `docker compose` не стартуют: `API_KEY` обязателен для сервиса `api`.

3. Запустите все сервисы:

   ```bash
   docker compose up --build -d
   ```

   Сервис `migrations` применяет `alembic upgrade head` и завершается с кодом 0; `api`, `consumer` и `outbox-relay` стартуют после него. Compose ждёт готовности PostgreSQL и RabbitMQ.

4. Проверьте состояние контейнеров и логи:

   ```bash
   docker compose ps
   curl -s http://localhost:8000/health
   docker compose logs --tail=100 api consumer outbox-relay
   ```

5. Панель RabbitMQ Management: <http://localhost:25673> (логин и пароль задаются в `.env`). В этом проекте внешний порт AMQP по умолчанию — `25672`; внутри Docker-сети сервисы используют `rabbitmq:5672`.

Остановить сервисы, сохранив данные в named volumes:

```bash
docker compose down
```

Удалять сохранённые данные следует только осознанно:

```bash
docker compose down -v
```

## Конфигурация

Основные переменные `.env`:

| Переменная | Назначение | Значение в `.env.example` |
|---|---|---|
| `API_KEY` | Ключ для REST API (обязателен для `api`) | Тестовый ключ |
| `ENABLE_DOCS` | Включает `/docs`, `/redoc`, `/openapi.json` | `false` |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | База PostgreSQL | `payments` / `payments` / `payments` |
| `RABBITMQ_DEFAULT_USER` / `RABBITMQ_DEFAULT_PASS` | Пользователь RabbitMQ | `payments` / `payments` |
| `DATABASE_URL` | SQLAlchemy async URL для запуска из Python | `postgresql+asyncpg://payments:payments@localhost:5432/payments` |
| `RABBITMQ_URL` | AMQP URL для запуска из Python | `amqp://payments:payments@localhost:25672/` |
| `OUTBOX_POLL_INTERVAL_SECONDS` | Интервал опроса Outbox relay-процессом | `1.0` |
| `OUTBOX_BATCH_SIZE` | Максимальное число событий в одном batch | `100` |

В контейнерах `DATABASE_URL` и `RABBITMQ_URL` собираются из переменных `POSTGRES_*`/`RABBITMQ_*` и указывают на хосты `postgres` и `rabbitmq`; в локальной среде — `localhost` и опубликованные порты.

## API

Бизнес-эндпоинты требуют заголовок `X-API-Key`. Для создания платежа также обязателен `Idempotency-Key`. Служебные эндпоинты `/health` и `/health/ready` публичные.

| Метод | Путь | Назначение | Успешный ответ |
|---|---|---|---|
| `POST` | `/api/v1/payments` | Создать платёж | `202 Accepted` |
| `GET` | `/api/v1/payments/{payment_id}` | Получить платёж и его статус | `200 OK` |
| `GET` | `/health` | Liveness (без проверки БД) | `200 OK` |
| `GET` | `/health/ready` | Readiness (проверка БД) | `200 OK`, `503` при недоступной БД |
| `GET` | `/docs`, `/redoc`, `/openapi.json` | Swagger UI и схема | `200 OK`, только при `ENABLE_DOCS=true` |

### Создание платежа

```bash
curl -X POST "http://localhost:8000/api/v1/payments" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -H "Idempotency-Key: order-123-payment-1" \
  -d '{
    "amount": "125.50",
    "currency": "RUB",
    "description": "Оплата заказа 123",
    "metadata": {"order_id": "123"},
    "webhook_url": "https://merchant.example/webhooks/payments"
  }'
```

Пример ответа:

```json
{
  "payment_id": "a87b9b5c-f8c6-4c3c-a978-63898cfbdbf1",
  "status": "pending",
  "created_at": "2026-10-12T10:30:00Z"
}
```

`pending` означает, что запрос принят, а асинхронная обработка ещё не завершена.

### Получение информации о платеже

```bash
curl "http://localhost:8000/api/v1/payments/a87b9b5c-f8c6-4c3c-a978-63898cfbdbf1" \
  -H "X-API-Key: $API_KEY"
```

Платёж содержит сумму, валюту, описание, `metadata`, статус, webhook URL и временные метки `created_at` / `processed_at`.

### Идемпотентность

- Повтор запроса с тем же `Idempotency-Key` и эквивалентными данными возвращает исходный платёж (`202`).
- Использование того же ключа с другими данными возвращает `409 Conflict`.
- Уникальность ключа обеспечивается ограничением PostgreSQL, а не только предварительным запросом к базе; гонка одинаковых ключей обрабатывается `IntegrityError` и повторной сверкой хеша.
- Канонический SHA-256 хеш запроса сохраняется в `request_hash`; порядок ключей JSON-объекта не влияет на вычисленный хеш.
- Создание платежа и события Outbox выполняются в одном Unit of Work: атомарность гарантирована одной транзакцией.

### Ошибки API

Единый формат ответа:

```json
{"error": {"code": "not_found", "message": "Payment not found"}}
```

| Код | `code` | Значение |
|---|---|---|
| `401` | `unauthorized` | API key отсутствует или неверен |
| `404` | `not_found` | Платёж не найден |
| `409` | `idempotency_conflict` | Idempotency key повторно использован с другим запросом |
| `422` | `validation_error` / `domain_error` | Некорректное тело запроса, заголовок или доменное правило |
| `503` | `not_ready` | `/health/ready`: база недоступна |

## Архитектурные решения

### Доменный слой отдельно от ORM

`Payment` — dataclass с бизнес-правилами: допустимые переходы `pending → succeeded|failed`, сравнение запроса с сохранённым хешем (`matches_request`). ORM-модели в `infrastructure/db/orm.py` — только маппинг таблиц, поэтому бизнес-логика не зависит от схемы БД и тестируется без неё.

### Репозитории и Unit of Work

Роутеры и use case'ы не работают с `AsyncSession`. Репозитории инкапсулируют SQL, Unit of Work — границы транзакции и `commit`/`rollback`. Это позволяет подменять хранилище в unit-тестах fake-реализациями и держит транзакционные границы в одном месте.

### Transactional Outbox

Запись платежа и запись события в `outbox` выполняются в одной транзакции PostgreSQL. Поэтому нельзя зафиксировать новый платёж, не сохранив одновременно событие для публикации. `outbox-relay` — отдельный процесс: он выбирает неопубликованные события (`FOR UPDATE SKIP LOCKED`), публикует их с publisher confirm и только затем в том же UoW ставит `published_at`.

### Семантика доставки

Доставка событий — **at-least-once**, а не exactly-once. Если relay упадёт после публикации в RabbitMQ, но до фиксации `published_at`, событие будет опубликовано повторно. Consumer идемпотентен: для платежа в финальном статусе шлюз не вызывается, повторяется только отправка webhook. Получатель webhook должен дедуплицировать уведомления по `event_id`.

### Повторные попытки

Consumer выполняет до трёх попыток: первоначальную, повтор через 2 секунды (`payments.retry.1`) и повтор через 4 секунды (`payments.retry.2`). Retry-очереди используют TTL и dead-letter routing обратно в exchange `payments`; номер попытки передаётся в заголовке `x-attempt`. После третьей неудачи сообщение публикуется в `payments.dlx` → `payments.dlq`.

### Платёж и webhook — разные этапы

Результат процессинга сохраняется в PostgreSQL до отправки webhook. Если webhook завершился ошибкой, сообщение уходит в retry, но платёж повторно не процессируется.

### Что не является production-ready

- Статический API key — упрощённая аутентификация для примера.
- Необходимо ограничивать и валидировать адреса webhook (включая защиту от SSRF), применять HTTPS и при необходимости подписывать запросы.
- Эмулируемый шлюз не моделирует идемпотентность настоящего внешнего платёжного провайдера.
- DLQ требует наблюдаемости, оповещений и документированной процедуры повторной обработки.
- Секреты, пароли и API key для реального окружения нужно хранить в менеджере секретов, а не в образе или репозитории.
- Один инстанс consumer'а не масштабируется по платежам «из коробки»; порядок и конкурентность обеспечиваются блокировкой строки и идемпотентностью обработки.

## Тестирование

Требуются Python из `pyproject.toml`, `uv` и PostgreSQL для интеграционных тестов. Создайте отдельную базу; `TEST_DATABASE_URL` должен указывать на имя, оканчивающееся на `_test` (по умолчанию `postgresql+asyncpg://payments:payments@localhost:5432/payments_test`).

```bash
uv sync
uv run ruff check src tests alembic

# unit + архитектурные тесты, без БД и брокера
uv run pytest -m "not e2e" -q

# только unit
uv run pytest tests/unit -q

# интеграционные API/репозитории против TEST_DATABASE_URL
uv run pytest -m integration -q

# retry → DLQ против живого RabbitMQ (нужен поднятый rabbitmq)
RABBITMQ_URL=amqp://payments:payments@127.0.0.1:25672/ uv run pytest -m rabbit -q

# e2e-сценарий против поднятого compose (POST → succeeded|failed → webhook)
docker compose up -d --build
E2E_API_KEY=$API_KEY uv run pytest -m e2e -q
```

Без доступной БД, брокера или запущенного стека соответствующие тесты пропускаются, а не падают. E2E-тест поднимает контейнер-приёмник webhook в сети compose и проверяет, что платёж дошёл до финального статуса и уведомление получено.

## Миграции

`alembic/` закоммичен в репозиторий (не в `.gitignore`). Применение миграций:

```bash
alembic upgrade head
```

В Docker Compose это делает одноразовый сервис `migrations`; `api`, `consumer` и `outbox-relay` ждут его успешного завершения.

## Структура проекта

```text
src/payment_service/
├── domain/                  # Payment, события, ошибки, порты (Protocol)
├── application/             # use case'ы: create/get/process/relay, hash идемпотентности
├── infrastructure/
│   ├── db/                  # ORM-модели, мапперы, репозитории, Unit of Work, session
│   ├── messaging/           # топология exchange/queue, публикатор FastStream
│   ├── gateway.py           # эмулятор платёжного шлюза
│   └── webhook.py           # отправка webhook через httpx
├── entrypoints/
│   ├── api/                 # FastAPI app, роутеры, DTO, зависимости, health, ошибки
│   ├── consumer.py          # FastStream consumer + retry/DLQ
│   └── outbox_relay.py      # отдельный процесс публикации Outbox
├── config.py                # конфигурация из окружения (pydantic-settings)
└── container.py             # сборка зависимостей
alembic/                     # env.py и versions/0001_initial.py
tests/
├── unit/                    # domain, application, схемы, архитектурные инварианты
├── integration/             # PostgreSQL: API, репозитории/UoW, retry→DLQ
└── e2e/                     # smoke против docker compose
Dockerfile
docker-compose.yml
pyproject.toml
uv.lock
.env.example
```
