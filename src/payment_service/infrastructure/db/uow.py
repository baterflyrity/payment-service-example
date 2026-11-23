from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payment_service.infrastructure.db.repositories import (
    SqlAlchemyOutboxRepository,
    SqlAlchemyPaymentRepository,
)


class SqlAlchemyUnitOfWork:
    """Единица работы: одна сессия/транзакция на все репозитории."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._committed = False

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        session = self._session_factory()
        self._session = session
        self._committed = False
        self.payments = SqlAlchemyPaymentRepository(session)
        self.outbox = SqlAlchemyOutboxRepository(session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self._session
        assert session is not None

        try:
            if exc_type is not None or not self._committed:
                await session.rollback()
        finally:
            await session.close()
            self._session = None

    async def commit(self) -> None:
        session = self._session
        assert session is not None

        await session.commit()
        self._committed = True

    async def rollback(self) -> None:
        session = self._session
        assert session is not None

        await session.rollback()
        self._committed = False
