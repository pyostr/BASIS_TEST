"""SQLAlchemy-репозиторий для сообщений outbox (адаптер порта домена)."""

from collections.abc import Callable
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.payments.domain.repositories.outbox import OutboxMessage
from src.app.payments.infrastructure.mappers.outbox import to_domain
from src.app.payments.infrastructure.models.outbox_message import OutboxMessageModel


class SqlAlchemyOutboxRepository:
    """SQLAlchemy-адаптер для порта домена репозитория outbox."""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory

    @property
    def _session(self) -> AsyncSession:
        return self._session_factory()

    async def claim_batch(self, limit: int) -> list[OutboxMessage]:
        """Забирает до ``limit`` необработанных сообщений (FOR UPDATE SKIP LOCKED).

        SKIP LOCKED позволяет конкурентным воркерам захватывать непересекающиеся
        пакеты, не блокируя друг друга.
        """
        result = await self._session.execute(
            select(OutboxMessageModel)
            .where(OutboxMessageModel.processed_at.is_(None))
            .order_by(OutboxMessageModel.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [to_domain(row) for row in result.scalars()]

    async def mark_processed(self, message_id: UUID) -> None:
        """Помечает сообщение как успешно опубликованное (устанавливает processed_at)."""
        await self._session.execute(
            update(OutboxMessageModel)
            .where(OutboxMessageModel.id == message_id)
            .values(processed_at=func.now())
        )

    async def mark_publish_failure(self, message_id: UUID) -> None:
        """Увеличивает счётчик попыток, не помечая сообщение обработанным.

        Сообщение остаётся доступным для повторного захвата при следующем опросе.
        """
        await self._session.execute(
            update(OutboxMessageModel)
            .where(OutboxMessageModel.id == message_id)
            .values(attempts=OutboxMessageModel.attempts + 1)
        )


__all__ = ['SqlAlchemyOutboxRepository']
