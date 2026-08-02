"""Порт персистентности для сущностей PaymentAttempt."""

from typing import Protocol

from src.app.payments.domain.entities.attempt import PaymentAttempt


class AttemptRepository(Protocol):
    """Контракт персистентности для сущностей PaymentAttempt.

    Реализации должны сохранять попытки в той же транзакции (единице
    работы), что и платёж, к которому они относятся.
    """

    async def add(self, attempt: PaymentAttempt) -> None:
        """Сохранить вновь созданную попытку."""

    async def get_by_payment_id(self, payment_id) -> list[PaymentAttempt]:
        """Вернуть все попытки платежа, упорядоченные по номеру попытки."""

    async def update(self, attempt: PaymentAttempt) -> None:
        """Сохранить изменения существующей попытки."""
