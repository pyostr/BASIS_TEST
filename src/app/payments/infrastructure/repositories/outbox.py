"""SQLAlchemy-репозиторий для сообщений outbox (адаптер порта домена)."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy import bindparam, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import DateTime as DateTimeType

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

    async def claim_batch(self, limit: int, now: datetime) -> list[OutboxMessage]:
        """Забирает до ``limit`` активных сообщений, чей ``next_retry_at`` наступил.

        ``FOR UPDATE SKIP LOCKED`` позволяет конкурентным воркерам захватывать
        непересекающиеся пакеты, не блокируя друг друга.
        """
        result = await self._session.execute(
            select(OutboxMessageModel)
            .where(
                OutboxMessageModel.processed_at.is_(None),
                OutboxMessageModel.status == 'pending',
                or_(
                    OutboxMessageModel.next_retry_at.is_(None),
                    OutboxMessageModel.next_retry_at <= now,
                ),
            )
            .order_by(OutboxMessageModel.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [to_domain(row) for row in result.scalars()]

    async def mark_processed(self, message_id: UUID) -> None:
        """Помечает сообщение как успешно опубликованное (устанавливает processed_at).

        Условное обновление защищает от повторной пометки, если другой воркер
        успел обработать строку между захватом и публикацией.
        """
        await self._session.execute(
            update(OutboxMessageModel)
            .where(
                OutboxMessageModel.id == message_id,
                OutboxMessageModel.processed_at.is_(None),
                OutboxMessageModel.status == 'pending',
            )
            .values(processed_at=func.now())
        )

    async def mark_publish_failure(
        self,
        message_id: UUID,
        *,
        max_attempts: int,
        next_retry_at: datetime | None,
    ) -> None:
        """Увеличивает счётчик попыток и откладывает повторный захват.

        При достижении ``max_attempts`` переводит сообщение в статус ``dead``;
        решение принимается по ``attempts`` в БД атомарно, чтобы конкурентные
        воркеры не могли обойти лимит попыток.
        """
        exceeded = OutboxMessageModel.attempts + 1 >= max_attempts
        next_retry = bindparam(
            'next_retry_at',
            value=next_retry_at,
            type_=DateTimeType(timezone=True),
        )
        await self._session.execute(
            update(OutboxMessageModel)
            .where(
                OutboxMessageModel.id == message_id,
                OutboxMessageModel.processed_at.is_(None),
                OutboxMessageModel.status == 'pending',
            )
            .values(
                attempts=OutboxMessageModel.attempts + 1,
                status=case((exceeded, 'dead'), else_='pending'),
                next_retry_at=case((exceeded, None), else_=next_retry),
            )
        )


__all__ = ['SqlAlchemyOutboxRepository']
