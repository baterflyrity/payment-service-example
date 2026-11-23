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

   В Windows PowerShell используйте `Copy-Item .env.example .env`. Файл `.env` не следует коммитить.

3. **Обязательно** сгенерируйте API-ключ и подставьте его в `.env` (шаг нельзя пропустить):

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   Полученную строку укажите в `.env` как `API_KEY=...`. Ключ должен быть не короче 32 символов; значения `change-me` и пустой ключ сервис не принимает. В том же файле замените `POSTGRES_PASSWORD`, `RABBITMQ_DEFAULT_PASS` и соответствующие пароли в `DATABASE_URL`/`RABBITMQ_URL` на собственные.

   После `cp .env.example .env` без замены `API_KEY` сервис `api` намеренно не стартует с ошибкой вида `API_KEY must be changed from the 'change-me' placeholder`. Без `.env` команды `docker compose` падают ещё раньше: `${API_KEY:?...}` требует явной установки ключа.

4. Запустите все сервисы:

   ```bash
   docker compose up --build -d
   ```

   Сервис `migrations` применяет `alembic upgrade head` и завершается с кодом 0; `api`, `consumer` и `outbox-relay` стартуют после него. Compose ждёт готовности PostgreSQL и RabbitMQ.

5. Проверьте состояние контейнеров и логи:

   ```bash
   docker compose ps
   curl -s http://localhost:8000/health
   docker compose logs --tail=100 api consumer outbox-relay
   ```

6. Панель RabbitMQ Management: <http://localhost:25673> (логин и пароль задаются в `.env`). В этом проекте внешний порт AMQP по умолчанию — `25672`; внутри Docker-сети сервисы используют `rabbitmq:5672`.

Контейнеры `api`, `consumer`, `outbox-relay` и `migrations` запускаются от непривилегированного пользователя `app` (UID 10001), с `cap_drop: [ALL]`, `no-new-privileges` и read-only корневой файловой системой (`/tmp` — tmpfs).

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
| `API_KEY` | Ключ для REST API (обязателен, минимум 32 символа) | `change-me` (заменить) |
| `ENABLE_DOCS` | Включает `/docs`, `/redoc`, `/openapi.json` | `false` |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | База PostgreSQL | `payments` / `payments` / `change-me` |
| `RABBITMQ_DEFAULT_USER` / `RABBITMQ_DEFAULT_PASS` | Пользователь RabbitMQ | `payments` / `change-me` |
| `DATABASE_URL` | SQLAlchemy async URL для запуска из Python | `postgresql+asyncpg://payments:change-me@localhost:5432/payments` |
| `RABBITMQ_URL` | AMQP URL для запуска из Python | `amqp://payments:change-me@localhost:25672/` |
| `WEBHOOK_ALLOW_HTTP` | Разрешает `http://` для webhook (local/e2e only) | `false` |
| `WEBHOOK_ALLOWED_HOSTS` | Доверенные хосты webhook через запятую (обход проверки адресов) | пусто |
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

Ограничения запроса:

- `description` — не длиннее 500 символов, `Idempotency-Key` — не длиннее 255 и не пустой.
- `metadata` — не более 16 КБ сериализованного JSON и не более 5 уровней вложенности.
- `webhook_url` — только `https` (либо `http` при `WEBHOOK_ALLOW_HTTP=true`); IP-литералы, `localhost`/`*.localhost` и URL с `user:pass@` отклоняются с `422`.

Перед отправкой webhook consumer повторно резолвит хост и отклоняет loopback, private, link-local, multicast, reserved и unspecified адреса (включая IPv4-mapped IPv6). Редиректы не выполняются. Запрещённый адрес не повторяется: сообщение сразу уходит в `payments.dlq`, а сохранённый статус платежа не меняется. Для локального стенда хост можно внести в `WEBHOOK_ALLOWED_HOSTS` (только через окружение).

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

Реализованные меры безопасности:

- Обязательный API-ключ без значения по умолчанию: плейсхолдер `change-me`, пустой ключ и ключи короче 32 символов не проходят валидацию, сервис не стартует.
- SSRF-защита webhook: https-only (с явным флагом для http), запрет IP-литералов, localhost и userinfo на входе; проверка всех DNS-адресов перед каждой отправкой, учёт IPv4-mapped IPv6, `follow_redirects=False`.
- Непривилегированные контейнеры: UID 10001, `cap_drop: [ALL]`, `no-new-privileges`, read-only rootfs.
- Лимиты входных данных: 16 КБ и 5 уровней вложенности для `metadata`, ограниченные `description` и `Idempotency-Key`.

Известные ограничения (не production-ready):

- Статический API key — упрощённая аутентификация для примера; нет подписи webhook (HMAC), rate limiting и защиты от перебора ключа.
- Эмулируемый шлюз не моделирует идемпотентность настоящего внешнего платёжного провайдера.
- DLQ требует наблюдаемости, оповещений и документированной процедуры повторной обработки.
- Секреты, пароли и API key для реального окружения нужно хранить в менеджере секретов, а не в образе или репозитории.
- Один инстанс consumer'а не масштабируется по платежам «из коробки»; порядок и конкурентность обеспечиваются блокировкой строки и идемпотентностью обработки.

## Тестирование

Требуются Python из `pyproject.toml`, `uv` и PostgreSQL для интеграционных тестов. Создайте отдельную базу; `TEST_DATABASE_URL` должен указывать на имя, оканчивающееся на `_test` (по умолчанию `postgresql+asyncpg://payments:change-me@localhost:5432/payments_test`; пароль должен совпадать с `POSTGRES_PASSWORD` из `.env`).

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
RABBITMQ_URL=amqp://payments:change-me@127.0.0.1:25672/ uv run pytest -m rabbit -q

# e2e-сценарий против поднятого compose (POST → succeeded|failed → webhook)
# Приёмник webhook живёт в сети compose, поэтому до запуска стека разрешите
# http для api/consumer и хост приёмника (имя контейнера) для consumer:
#   WEBHOOK_ALLOW_HTTP=true
#   WEBHOOK_ALLOWED_HOSTS=e2e-webhook-receiver
# в .env, затем `docker compose up -d --build`.
E2E_API_KEY=$API_KEY uv run pytest -m e2e -q
```

Для запуска тестов из Python нужен валидный `API_KEY`: создайте `.env` по инструкции выше (или экспортируйте переменную окружения) — без него конфигурация не загрузится так же, как и у сервиса. Без доступной БД, брокера или запущенного стека соответствующие тесты пропускаются, а не падают. E2E-тест поднимает контейнер-приёмник webhook в сети compose и проверяет, что платёж дошёл до финального статуса и уведомление получено.

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
