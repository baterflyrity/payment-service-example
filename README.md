# Payment Service Example

Асинхронный микросервис приёма и обработки платежей. Проект демонстрирует REST API на FastAPI, хранение состояния в PostgreSQL, надёжную публикацию событий через **Transactional Outbox**, обработку сообщений в RabbitMQ и уведомление клиента через webhook.


## Возможности

- Создание платежа и получение его статуса через REST API.
- Аутентификация статическим API-ключом в `X-API-Key`.
- Идемпотентность запросов по `Idempotency-Key` с проверкой идентичности данных.
- Асинхронное хранение событий в Outbox в одной транзакции с платежом.
- Публикация событий в RabbitMQ с возможностью повторной отправки после сбоя брокера.
- Consumer на FastStream: имитация платёжного шлюза (2–5 секунд; 90% `succeeded`, 10% `failed`).
- Повторная доставка после технических ошибок с задержками 2 и 4 секунды; затем сообщение попадает в DLQ.
- Webhook с результатом обработки платежа.
- Миграции Alembic и контейнерный запуск через Docker Compose.
- Unit-, интеграционные API- и end-to-end тесты.

## Архитектура

### Компоненты и связи

```mermaid
flowchart LR
    Client[Клиент] -->|HTTP + API key| API[FastAPI API]
    API -->|Одна транзакция| DB[(PostgreSQL)]
    DB --- Payments[Таблица payments]
    DB --- Outbox[Таблица outbox]
    Outbox -->|Опрос неопубликованных событий| Publisher[Outbox publisher]
    Publisher -->|payments.new| Rabbit[(RabbitMQ)]
    Rabbit --> Consumer[FastStream consumer]
    Consumer -->|Чтение и обновление статуса| DB
    Consumer -->|HTTP POST с результатом| Webhook[Webhook клиента]
    Consumer -->|Техническая ошибка| Retry[Retry queues: TTL 2s / 4s]
    Retry -->|Dead-letter routing| Rabbit
    Consumer -->|Третья неудачная попытка| DLQ[(payments.dlq)]
```

### Создание и обработка платежа

```mermaid
sequenceDiagram
    autonumber
    participant C as Клиент
    participant A as FastAPI
    participant P as PostgreSQL
    participant O as Outbox publisher
    participant R as RabbitMQ
    participant W as Consumer
    participant H as Webhook клиента

    C->>A: POST /api/v1/payments
    A->>P: BEGIN
    A->>P: INSERT payments + outbox
    P-->>A: COMMIT
    A-->>C: 202 Accepted, payment_id, pending
    loop Периодический опрос
        O->>P: SELECT pending events FOR UPDATE SKIP LOCKED
        O->>R: Publish payments.new
        R-->>O: Успешная публикация
        O->>P: Set published_at
    end
    R->>W: Событие payments.new
    W->>P: Прочитать платёж
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
    C -->|Ошибка, попытка 1| R2[payments.retry.2s<br/>TTL = 2 секунды]
    R2 -->|После TTL через DLX| Q
    C -->|Ошибка, попытка 2| R4[payments.retry.4s<br/>TTL = 4 секунды]
    R4 -->|После TTL через DLX| Q
    C -->|Ошибка, попытка 3| DLQ[(payments.dlq)]
```


## Технологии

- Python 3.14
- FastAPI, Pydantic v2
- SQLAlchemy async, asyncpg, PostgreSQL
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

   В Windows PowerShell используйте `Copy-Item .env.example .env`. Установите собственный `API_KEY` и замените тестовые пароли PostgreSQL и RabbitMQ. Файл `.env` не следует коммитить.

3. Запустите все сервисы:

   ```bash
   docker compose up --build -d
   ```

   API-сервис применяет миграции Alembic перед запуском Uvicorn. Compose ждёт готовности PostgreSQL и RabbitMQ.

4. Проверьте состояние контейнеров и логи:

   ```bash
   docker compose ps
   docker compose logs --tail=100 api
   docker compose logs --tail=100 consumer
   ```

5. Откройте документацию API: <http://localhost:8000/docs>.

   Панель RabbitMQ Management: <http://localhost:25673> (логин и пароль задаются в `.env`). В этом проекте внешний порт AMQP по умолчанию — `25672`. Внутри Docker-сети сервисы используют `rabbitmq:5672`.

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

| Переменная | Назначение | Значение для локальной разработки в примере |
|---|---|---|
| `API_KEY` | Ключ для REST API | Задайте свой |
| `POSTGRES_DB` | Имя базы PostgreSQL | `payments` |
| `POSTGRES_USER` | Пользователь PostgreSQL | `payments` |
| `POSTGRES_PASSWORD` | Пароль PostgreSQL | Задайте свой |
| `RABBITMQ_DEFAULT_USER` | Пользователь RabbitMQ | `payments` |
| `RABBITMQ_DEFAULT_PASS` | Пароль RabbitMQ | Задайте свой |
| `DATABASE_URL` | SQLAlchemy async URL для локального запуска из Python | `postgresql+asyncpg://payments:payments@localhost:5432/payments` |
| `RABBITMQ_URL` | AMQP URL для локального запуска из Python | `amqp://payments:payments@localhost:25672/` |
| `OUTBOX_POLL_INTERVAL_SECONDS` | Интервал опроса Outbox | `1.0` |
| `OUTBOX_BATCH_SIZE` | Максимальное число событий в одном batch | `100` |

В контейнерах используются сетевые имена сервисов `postgres` и `rabbitmq`; в локальной среде — `localhost` и опубликованные порты. Проверьте, что `.env.example` согласован с конфигурацией текущей версии `docker-compose.yml`.

## API

Все бизнес-эндпоинты требуют заголовок `X-API-Key`. Для создания платежа также обязателен `Idempotency-Key`.

| Метод | Путь | Назначение | Успешный ответ |
|---|---|---|---|
| `POST` | `/api/v1/payments` | Создать платёж | `202 Accepted` |
| `GET` | `/api/v1/payments/{payment_id}` | Получить платёж и его статус | `200 OK` |
| `GET` | `/docs` | Swagger UI | `200 OK` |
| `GET` | `/openapi.json` | OpenAPI-спецификация, используется в healthcheck | `200 OK` |

### Создание платежа

Пример для Bash:

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

Идентификатор и время в примере условные. `pending` означает, что запрос принят, а асинхронная обработка ещё не завершена.

### Получение информации о платеже

```bash
curl "http://localhost:8000/api/v1/payments/a87b9b5c-f8c6-4c3c-a978-63898cfbdbf1" \
  -H "X-API-Key: $API_KEY"
```

Платёж содержит сумму, валюту, описание, `metadata`, статус, webhook URL и временные метки `created_at` / `processed_at`.

### Идемпотентность

- Повтор запроса с тем же `Idempotency-Key` и эквивалентными данными возвращает исходный платёж.
- Использование того же ключа с другими данными возвращает `409 Conflict`.
- Уникальность ключа обеспечивается ограничением PostgreSQL, а не только предварительным запросом к базе.
- Канонический SHA-256 хеш запроса сохраняется в `request_hash`; порядок ключей JSON-объекта не влияет на вычисленный хеш.

### Ошибки API

| Код | Значение |
|---|---|
| `401` | API key отсутствует или неверен |
| `404` | Платёж не найден |
| `409` | Idempotency key повторно использован с другим запросом |
| `422` | Некорректное тело запроса или отсутствующий обязательный заголовок |
| `202` | Платёж принят к асинхронной обработке |

## Архитектурные гарантии и ограничения

### Transactional Outbox

Запись платежа и запись события в `outbox` выполняются в одной транзакции PostgreSQL. Поэтому нельзя зафиксировать новый платёж, не сохранив одновременно событие для публикации. Publisher выбирает неопубликованные события и устанавливает `published_at` только после успешной публикации.

### Семантика доставки

Доставка событий — **at-least-once**, а не exactly-once. Если процесс завершится после публикации в RabbitMQ, но до фиксации `published_at`, событие может быть опубликовано повторно. Consumer должен оставаться идемпотентным.

### Повторные попытки

Consumer выполняет до трёх попыток: первоначальную, повтор через 2 секунды и повтор через 4 секунды. Retry-очереди используют TTL и dead-letter routing. После третьей неудачи сообщение отправляется в `payments.dlq`.

### Платёж и webhook — разные этапы

Результат эмулируемого процессинга сохраняется в PostgreSQL до отправки webhook. При повторной доставке события с уже конечным статусом (`succeeded` / `failed`) шлюз не запускается повторно: consumer повторяет доставку webhook. Получатель webhook должен дедуплицировать события по `event_id`, потому что HTTP-ответ может потеряться после фактической обработки уведомления получателем.

### Что не является production-ready

- Статический API key — упрощённая аутентификация для примера.
- Необходимо ограничивать и валидировать адреса webhook (включая защиту от SSRF), применять HTTPS и при необходимости подписывать запросы.
- Эмулируемый шлюз не моделирует идемпотентность настоящего внешнего платёжного провайдера.
- DLQ требует наблюдаемости, оповещений и документированной процедуры повторной обработки.
- Секреты, пароли и API key для реального окружения нужно хранить в менеджере секретов, а не в образе или репозитории.

## Тестирование

Для локального запуска тестов требуются Python из `pyproject.toml`, `uv` и PostgreSQL. Создайте отдельную базу тестирования; тестовая конфигурация должна указывать на имя базы, оканчивающееся на `_test` (например, `payments_test`). Обычные тесты используют отдельную тестовую БД и не должны запускаться против `payments`.

```bash
uv sync
uv run ruff check src tests
uv run pytest -v
```

Текущий набор включает валидацию Pydantic-схем, вычисление idempotency hash, API-тесты (статусы HTTP, авторизация, идемпотентность, создание Outbox), тесты publisher и обработчика платежа.

## Структура проекта

```text
src/payment_service/
├── api/             # FastAPI endpoints и API key dependency
├── messaging/       # Объявление RabbitMQ queues
├── models/          # SQLAlchemy models: Payment и Outbox
├── schemas/         # Pydantic request/response/event schemas
├── services/        # Хеширование idempotency key и процессинг
├── workers/         # Outbox publisher и RabbitMQ consumer
├── config.py        # Конфигурация из окружения
└── db.py            # Async SQLAlchemy engine и session factory
alembic/             # Миграции PostgreSQL
tests/              # Unit и интеграционные тесты
Dockerfile
docker-compose.yml
pyproject.toml
uv.lock
.env.example
```
