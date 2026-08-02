"""Порт персистентности для агрегата Payment с оптимистичной блокировкой."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from src.app.payments.domain.aggregates.payment import Payment, PaymentStatus


class PaymentRepository(Protocol):
    """Порт персистентности для Payment.

    Методы с оптимистичной блокировкой должны применять переход состояния
    атомарно и сообщать о конфликте возвратом False.
    """

    async def try_insert(self, payment: Payment) -> Payment | None:
        """Атомарно вставить платёж; вернуть None, если idempotency_key уже существует."""
        ...

    async def get(self, payment_id: UUID) -> Payment | None:
        """Загрузить платёж по идентификатору или None, если его нет."""

    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        """Загрузить платёж по ключу идемпотентности, предоставленному клиентом, или None."""

    async def begin_processing(
        self,
        payment_id: UUID,
        expected_version: int,
        expected_status: PaymentStatus,
    ) -> bool:
        """Атомарно перевести pending -> processing; False при конфликте.

        ``expected_status`` — статус, в котором платёж находится в базе на
        момент захвата (источник правды — конечный автомат агрегата).
        """

    async def mark_succeeded(
        self,
        payment_id: UUID,
        expected_version: int,
        expected_status: PaymentStatus,
        processed_at: datetime,
    ) -> bool:
        """Атомарно перевести processing -> succeeded; False при конфликте версий."""

    async def mark_failed(
        self,
        payment_id: UUID,
        expected_version: int,
        expected_status: PaymentStatus,
        processed_at: datetime,
    ) -> bool:
        """Атомарно перевести processing -> failed; False при конфликте версий."""
