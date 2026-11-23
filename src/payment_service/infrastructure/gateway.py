"""Эмулятор внешнего платёжного шлюза."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from decimal import Decimal
from uuid import UUID

from payment_service.domain.payment import Currency

Sleep = Callable[[float], Awaitable[None]]


class RandomPaymentGateway:
    """Случайный результат: 90% succeeded, 10% failed.

    Задержка 2–5 с, вероятность и параметры сна настраиваются для тестов.
    Row lock в базе на время вызова не удерживается.
    """

    def __init__(
        self,
        *,
        min_delay_seconds: float = 2.0,
        max_delay_seconds: float = 5.0,
        success_rate: float = 0.9,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        if min_delay_seconds < 0:
            raise ValueError("min_delay_seconds must not be negative")
        if max_delay_seconds < min_delay_seconds:
            raise ValueError("max_delay_seconds must be >= min_delay_seconds")
        if not 0.0 <= success_rate <= 1.0:
            raise ValueError("success_rate must be between 0 and 1")

        self._min_delay = min_delay_seconds
        self._max_delay = max_delay_seconds
        self._success_rate = success_rate
        self._sleep = sleep
        self._rng = rng or random.Random()

    async def process(
        self,
        payment_id: UUID,
        amount: Decimal,
        currency: Currency,
    ) -> bool:
        del payment_id, amount, currency

        await self._sleep(self._rng.uniform(self._min_delay, self._max_delay))

        return self._rng.random() < self._success_rate
