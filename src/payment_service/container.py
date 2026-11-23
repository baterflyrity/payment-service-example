from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends

from payment_service.application.create_payment import CreatePaymentService
from payment_service.application.get_payment import GetPaymentService
from payment_service.domain.ports import UnitOfWork
from payment_service.infrastructure.db.session import SessionFactory
from payment_service.infrastructure.db.uow import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], UnitOfWork]


def utcnow() -> datetime:
    return datetime.now(UTC)


def make_unit_of_work() -> UnitOfWork:
    return SqlAlchemyUnitOfWork(SessionFactory)


def get_unit_of_work_factory() -> UnitOfWorkFactory:
    """Фабрика UoW; в тестах подменяется на тестовую БД."""

    return make_unit_of_work


def get_create_payment_service(
    uow_factory: Annotated[UnitOfWorkFactory, Depends(get_unit_of_work_factory)],
) -> CreatePaymentService:
    return CreatePaymentService(uow_factory=uow_factory, clock=utcnow)


def get_payment_service(
    uow_factory: Annotated[UnitOfWorkFactory, Depends(get_unit_of_work_factory)],
) -> GetPaymentService:
    return GetPaymentService(uow_factory=uow_factory)
