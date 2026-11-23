"""Отдельный процесс: публикация событий outbox в RabbitMQ."""

from __future__ import annotations

import asyncio
import logging
import signal

from faststream.rabbit import RabbitBroker

from payment_service.application.relay_outbox import RelayOutboxService
from payment_service.config import settings
from payment_service.container import make_unit_of_work
from payment_service.infrastructure.messaging.publisher import FastStreamEventPublisher
from payment_service.infrastructure.messaging.topology import (
    PAYMENTS_EXCHANGE,
    PAYMENTS_NEW_QUEUE,
    PAYMENTS_NEW_ROUTING_KEY,
)

logger = logging.getLogger(__name__)


async def declare_topology(broker: RabbitBroker) -> None:
    """Объявляет exchange ``payments`` и привязывает к нему очередь."""

    exchange = await broker.declare_exchange(PAYMENTS_EXCHANGE)
    queue = await broker.declare_queue(PAYMENTS_NEW_QUEUE)

    await queue.bind(exchange, routing_key=PAYMENTS_NEW_ROUTING_KEY)


async def run_relay(stop_event: asyncio.Event) -> None:
    """Публикует outbox партиями, переподключаясь после ошибок."""

    broker = RabbitBroker(settings.rabbitmq_url)
    service = RelayOutboxService(
        uow_factory=make_unit_of_work,
        publisher=FastStreamEventPublisher(broker),
        batch_size=settings.outbox_batch_size,
    )
    connected = False

    try:
        while not stop_event.is_set():
            try:
                if not connected:
                    await broker.connect()
                    await declare_topology(broker)
                    connected = True

                    logger.info(
                        "Connected to RabbitMQ; outbox relay is running",
                    )

                published = await service.run_once()

                if published:
                    logger.info(
                        "Outbox relay published %d event(s)",
                        published,
                    )

            except asyncio.CancelledError:
                raise

            except Exception:
                logger.exception(
                    "Outbox relay cycle failed; will reconnect and retry",
                )
                connected = False

                try:
                    await broker.stop()
                except Exception:
                    logger.exception(
                        "Failed to close RabbitMQ connection",
                    )

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=settings.outbox_poll_interval_seconds,
                )
            except TimeoutError:
                pass

    finally:
        await broker.stop()

        logger.info("Outbox relay stopped")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    await run_relay(stop_event)


if __name__ == "__main__":
    asyncio.run(main())
