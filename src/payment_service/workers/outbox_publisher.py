import asyncio
import logging
from datetime import UTC, datetime

from faststream.rabbit import RabbitBroker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payment_service.config import settings
from payment_service.db import SessionFactory
from payment_service.messaging.topology import PAYMENTS_NEW_QUEUE
from payment_service.models import Outbox

logger = logging.getLogger(__name__)


async def publish_outbox_batch(
    session_factory: async_sessionmaker[AsyncSession],
    broker: RabbitBroker,
    batch_size: int | None = None,
) -> int:
    """Publish a batch of pending events from the transactional outbox.

    Returns the number of events successfully published and marked as published.
    Unpublished events remain in the database and will be retried later.
    """

    limit = batch_size if batch_size is not None else settings.outbox_batch_size
    if limit < 1:
        raise ValueError("batch_size must be positive")

    published_count = 0

    async with session_factory() as session:
        async with session.begin():
            result = await session.scalars(
                select(Outbox).where(Outbox.published_at.is_(None)).order_by(Outbox.created_at, Outbox.id).limit(limit).with_for_update(skip_locked=True),
            )
            events = list(result.all())

            for event in events:
                event.attempts += 1

                try:
                    await broker.publish(
                        event.payload,
                        queue=PAYMENTS_NEW_QUEUE,
                        mandatory=True,
                        persist=True,
                        message_id=str(event.id),
                    )
                except Exception as exc:
                    event.last_error = (f"{type(exc).__name__}: {exc}")[:2000]

                    logger.exception(
                        "Failed to publish outbox event %s; it will be retried",
                        event.id,
                    )

                    # Avoid repeatedly sending a batch when RabbitMQ is down.
                    # The remaining events stay unpublished.
                    break

                event.published_at = datetime.now(UTC)
                event.last_error = None
                published_count += 1

                logger.info(
                    "Published outbox event %s, type=%s, aggregate_id=%s",
                    event.id,
                    event.event_type,
                    event.aggregate_id,
                )

    return published_count


async def run_outbox_publisher(
    stop_event: asyncio.Event,
    session_factory: async_sessionmaker[AsyncSession] = SessionFactory,
) -> None:
    """Continuously publish outbox events, reconnecting after failures."""

    broker: RabbitBroker | None = None

    try:
        while not stop_event.is_set():
            try:
                if broker is None:
                    broker = RabbitBroker(settings.rabbitmq_url)
                    await broker.connect()
                    await broker.declare_queue(PAYMENTS_NEW_QUEUE)

                    logger.info(
                        "Connected to RabbitMQ; outbox publisher is running",
                    )

                await publish_outbox_batch(
                    session_factory=session_factory,
                    broker=broker,
                )

            except asyncio.CancelledError:
                raise

            except Exception:
                logger.exception(
                    "Outbox publisher cycle failed; will reconnect and retry",
                )

                if broker is not None:
                    try:
                        await broker.close()
                    except Exception:
                        logger.exception(
                            "Failed to close RabbitMQ connection",
                        )

                    broker = None

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=settings.outbox_poll_interval_seconds,
                )
            except TimeoutError:
                pass

    finally:
        if broker is not None:
            await broker.stop()

        logger.info("Outbox publisher stopped")
