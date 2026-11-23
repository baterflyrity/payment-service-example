# T06. Обработка платежа, consumer, exchanges, retry, DLQ (F2, F5)

## Контекст
`docs/agent/ARCHITECTURE.md` (Consumer, Retry/DLQ), `domain/*`, `infrastructure/db/uow.py`, `src/payment_service/services/payment_processor.py`, `src/payment_service/workers/consumer.py`, `src/payment_service/messaging/topology.py`, `tests/test_consumer_retries.py`, `tests/test_payment_processor.py`.

## Сделать
1. `infrastructure/gateway.py` (2–5 с, 90/10; seed/вероятность настраиваемые для тестов), `infrastructure/webhook.py` (httpx, таймаут, не-2xx = ошибка, тело: `event_id, payment_id, status, amount, currency, processed_at`).
2. `application/process_payment.py`: `ProcessPaymentService`. UoW #1: `get_for_update`; если не финальный — вызвать шлюз **вне транзакции с блокировкой** (или короткая блокировка + повторная проверка), затем UoW #2: `mark_succeeded/failed` + commit. Если уже финальный — шлюз не вызывается. Затем webhook. Ошибка webhook → исключение (для retry).
3. `infrastructure/messaging/topology.py`: exchanges `payments` (direct), `payments.retry` (direct), `payments.dlx` (direct); очереди `payments.new`, `payments.retry.1` (TTL 2s), `payments.retry.2` (TTL 4s) с DLX→`payments`/`payments.new`, `payments.dlq`. Все durable.
4. `entrypoints/consumer.py`: тонкий хендлер FastStream: парсинг → сервис → ack; при исключении — номер попытки из заголовка `x-attempt`; попытка < 3 → publish в retry; иначе → `payments.dlx` с `x-last-error`; затем ack оригинала.

## Границы
Не трогать API и relay (кроме общей topology).

## Критерии готовности
- Unit (fakes): финальный статус не перепроцессируется; webhook-ошибка → исключение; 1-я и 2-я ошибка → retry-очереди с правильными задержками, 3-я → DLQ.
- Интеграционный тест с RabbitMQ (pytest marker `rabbit`, скип при недоступности): сообщение с постоянно падающим webhook оказывается в `payments.dlq` примерно через 6 с.
- Нет `sqlalchemy` вне `infrastructure/`.
