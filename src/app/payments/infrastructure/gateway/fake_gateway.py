"""Фейковый адаптер платёжного шлюза для локальной разработки и тестов.

Реализует порт домена ``PaymentGateway`` с настраиваемой задержкой и
стохастическим исходом «успех/отказ», поэтому внешний сервис не требуется.
"""

import asyncio
import random
import uuid
from datetime import UTC, datetime
from uuid import UUID

from src.app.payments.domain.gateway import GatewayResult
from src.app.payments.domain.value_objects.money import Money


class FakeGateway:
    """Эмулирует внешний платёжный шлюз.

    Ждёт ``min_delay..max_delay`` секунд и возвращает бизнес-результат:
    успех с вероятностью ``1 - failure_rate``, иначе отказ.
    """

    def __init__(
        self,
        min_delay: float = 2.0,
        max_delay: float = 5.0,
        failure_rate: float = 0.1,
        rng: random.Random | None = None,
    ) -> None:
        """Настраивает границы задержки, вероятность отказа и ГСЧ."""
        if min_delay < 0 or max_delay < min_delay:
            raise ValueError('Invalid gateway delay bounds')
        if not 0 <= failure_rate <= 1:
            raise ValueError('failure_rate must be in [0, 1]')

        self._min_delay = min_delay
        self._max_delay = max_delay
        self._failure_rate = failure_rate
        self._rng = rng or random.Random()

    async def charge(
        self,
        payment_id: UUID,
        amount: Money,
        idempotency_key: str,
    ) -> GatewayResult:
        """Списывает платёж после имитируемой задержки.

        Возвращает успешный ``GatewayResult`` (с новым gateway id) с
        вероятностью ``1 - failure_rate``, иначе результат с отказом.
        """
        delay = self._rng.uniform(self._min_delay, self._max_delay)
        await asyncio.sleep(delay)

        if self._rng.random() < self._failure_rate:
            return GatewayResult(
                success=False,
                error='Gateway declined the transaction',
                raw={
                    'provider': 'fake',
                    'payment_id': str(payment_id),
                    'idempotency_key': idempotency_key,
                    'amount': str(amount.amount),
                    'currency': amount.currency.value,
                    'declined_at': datetime.now(UTC).isoformat(),
                },
            )

        return GatewayResult(
            success=True,
            gateway_id=str(uuid.uuid4()),
            raw={
                'provider': 'fake',
                'payment_id': str(payment_id),
                'idempotency_key': idempotency_key,
                'amount': str(amount.amount),
                'currency': amount.currency.value,
                'charged_at': datetime.now(UTC).isoformat(),
            },
        )


__all__ = ['FakeGateway']
