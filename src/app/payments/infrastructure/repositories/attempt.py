"""SQLAlchemy-репозиторий для попыток платежей (адаптер порта домена)."""

from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.payments.domain.entities.attempt import PaymentAttempt
from src.app.payments.infrastructure.mappers.attempt import to_domain
from src.app.payments.infrastructure.models.payment_attempt import PaymentAttemptModel


class SqlAlchemyAttemptRepository:
    """SQLAlchemy-адаптер для порта домена репозитория попыток."""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory

    @property
    def _session(self) -> AsyncSession:
        return self._session_factory()

    async def add(self, attempt: PaymentAttempt) -> None:
        """Помещает новую строку попытки в текущую сессию (ещё не зафлашена)."""
        self._session.add(
            PaymentAttemptModel(
                id=attempt.id,
                payment_id=attempt.payment_id,
                attempt_number=attempt.attempt_number,
                status=attempt.status.value,
                error=attempt.error,
                gateway_response=attempt.gateway_response,
                correlation_id=attempt.correlation_id,
                created_at=attempt.created_at,
                updated_at=attempt.updated_at,
            )
        )

    async def update(self, attempt: PaymentAttempt) -> None:
        """Сохраняет изменяемые поля (status, error, ответ шлюза) по id."""
        await self._session.execute(
            update(PaymentAttemptModel)
            .where(PaymentAttemptModel.id == attempt.id)
            .values(
                status=attempt.status.value,
                error=attempt.error,
                gateway_response=attempt.gateway_response,
                updated_at=attempt.updated_at,
            )
        )

    async def get_by_payment_id(self, payment_id: UUID) -> list[PaymentAttempt]:
        """Возвращает все попытки платежа, упорядоченные по времени создания."""
        result = await self._session.execute(
            select(PaymentAttemptModel)
            .where(PaymentAttemptModel.payment_id == payment_id)
            .order_by(
                PaymentAttemptModel.created_at, PaymentAttemptModel.attempt_number
            )
        )
        return [to_domain(row) for row in result.scalars()]


__all__ = ['SqlAlchemyAttemptRepository']
