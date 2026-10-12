from faststream.rabbit import RabbitQueue

PAYMENTS_NEW_QUEUE = RabbitQueue(
    name="payments.new",
    durable=True,
)

PAYMENTS_RETRY_2S_QUEUE = RabbitQueue(
    name="payments.retry.2s",
    durable=True,
    arguments={
        "x-message-ttl": 2_000,
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": "payments.new",
    },
)

PAYMENTS_RETRY_4S_QUEUE = RabbitQueue(
    name="payments.retry.4s",
    durable=True,
    arguments={
        "x-message-ttl": 4_000,
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": "payments.new",
    },
)

PAYMENTS_DLQ = RabbitQueue(
    name="payments.dlq",
    durable=True,
)

MAX_PROCESSING_ATTEMPTS = 3

RETRY_QUEUES = {
    1: PAYMENTS_RETRY_2S_QUEUE,
    2: PAYMENTS_RETRY_4S_QUEUE,
}
