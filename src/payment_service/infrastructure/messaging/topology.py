"""Топология RabbitMQ: основной, retry- и DLX-exchange, очереди и DLQ.

Все объявления durable и создаются идемпотентно. Retry-очереди держат
сообщение TTL (2 с и 4 с), после чего dead-letter возвращает его в
exchange ``payments`` с routing key ``payments.new``.
"""

from __future__ import annotations

from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue

PAYMENTS_EXCHANGE = RabbitExchange(
    name="payments",
    type=ExchangeType.DIRECT,
    durable=True,
)

PAYMENTS_RETRY_EXCHANGE = RabbitExchange(
    name="payments.retry",
    type=ExchangeType.DIRECT,
    durable=True,
)

PAYMENTS_DLX_EXCHANGE = RabbitExchange(
    name="payments.dlx",
    type=ExchangeType.DIRECT,
    durable=True,
)

PAYMENTS_NEW_ROUTING_KEY = "payments.new"
PAYMENTS_DLQ_ROUTING_KEY = "payments.dlq"

PAYMENTS_NEW_QUEUE = RabbitQueue(
    name="payments.new",
    durable=True,
    routing_key=PAYMENTS_NEW_ROUTING_KEY,
)

PAYMENTS_RETRY_2S_QUEUE = RabbitQueue(
    name="payments.retry.1",
    durable=True,
    routing_key="payments.retry.1",
    arguments={
        "x-message-ttl": 2_000,
        "x-dead-letter-exchange": "payments",
        "x-dead-letter-routing-key": PAYMENTS_NEW_ROUTING_KEY,
    },
)

PAYMENTS_RETRY_4S_QUEUE = RabbitQueue(
    name="payments.retry.2",
    durable=True,
    routing_key="payments.retry.2",
    arguments={
        "x-message-ttl": 4_000,
        "x-dead-letter-exchange": "payments",
        "x-dead-letter-routing-key": PAYMENTS_NEW_ROUTING_KEY,
    },
)

PAYMENTS_DLQ = RabbitQueue(
    name="payments.dlq",
    durable=True,
    routing_key=PAYMENTS_DLQ_ROUTING_KEY,
)

MAX_PROCESSING_ATTEMPTS = 3

# Номер попытки -> retry-очередь, в которую уходит сообщение после её провала.
RETRY_QUEUES = {
    1: PAYMENTS_RETRY_2S_QUEUE,
    2: PAYMENTS_RETRY_4S_QUEUE,
}


async def declare_topology(broker: RabbitBroker) -> None:
    """Объявляет exchanges, очереди и привязки (идемпотентно)."""

    payments_exchange = await broker.declare_exchange(PAYMENTS_EXCHANGE)
    retry_exchange = await broker.declare_exchange(PAYMENTS_RETRY_EXCHANGE)
    dlx_exchange = await broker.declare_exchange(PAYMENTS_DLX_EXCHANGE)

    new_queue = await broker.declare_queue(PAYMENTS_NEW_QUEUE)
    await new_queue.bind(payments_exchange, routing_key=PAYMENTS_NEW_ROUTING_KEY)

    for retry_queue in (PAYMENTS_RETRY_2S_QUEUE, PAYMENTS_RETRY_4S_QUEUE):
        declared = await broker.declare_queue(retry_queue)
        await declared.bind(retry_exchange, routing_key=retry_queue.name)

    dlq = await broker.declare_queue(PAYMENTS_DLQ)
    await dlq.bind(dlx_exchange, routing_key=PAYMENTS_DLQ_ROUTING_KEY)
