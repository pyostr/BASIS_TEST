"""SQLAlchemy-репозиторий для сообщений outbox (адаптер порта домена)."""

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import bindparam, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import DateTime as DateTimeType

from src.app.payments.domain.repositories.outbox import OutboxMessage
from src.app.payments.infrastructure.mappers.outbox import to_domain
from src.app.payments.infrastructure.models.outbox_message import OutboxMessageModel

PENDING = 'pending'
PROCESSING = 'processing'
DEAD = 'dead'


class SqlAlchemyOutboxRepository:
    """SQLAlchemy-адаптер для порта домена репозитория outbox."""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory

    @property
    def _session(self) -> AsyncSession:
        return self._session_factory()

    async def release_expired_claims(self, now: datetime, timeout: int) -> None:
        """Возвращает просроченные lease в статус ``pending``.

        Упавший воркер (claim без mark) блокирует сообщение не дольше, чем на
        ``timeout`` секунд, после чего оно снова доступно для захвата.
        """
        cutoff = now - timedelta(seconds=timeout)
        await self._session.execute(
            update(OutboxMessageModel)
            .where(
                OutboxMessageModel.status == PROCESSING,
                OutboxMessageModel.claimed_at.is_not(None),
                OutboxMessageModel.claimed_at < cutoff,
            )
            .values(
                status=PENDING,
                claimed_at=None,
                claimed_by=None,
            )
        )

    async def claim_batch(
        self, limit: int, now: datetime, worker_id: UUID
    ) -> list[OutboxMessage]:
        """Атомарно захватывает до ``limit`` активных сообщений.

        Подзапрос выбирает ``pending``-сообщения с наступившим ``next_retry_at``
        и блокирует их ``FOR UPDATE SKIP LOCKED`` (конкурентные воркеры получают
        непересекающиеся пакеты), затем единственное ``UPDATE`` переводит их в
        ``processing`` с владельцем, отметкой времени и инкрементом ``attempts``.
        """
        subquery = (
            select(OutboxMessageModel.id)
            .where(
                OutboxMessageModel.status == PENDING,
                OutboxMessageModel.processed_at.is_(None),
                or_(
                    OutboxMessageModel.next_retry_at.is_(None),
                    OutboxMessageModel.next_retry_at <= now,
                ),
            )
            .order_by(OutboxMessageModel.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.scalars(
            update(OutboxMessageModel)
            .where(OutboxMessageModel.id.in_(subquery))
            .values(
                status=PROCESSING,
                claimed_at=now,
                claimed_by=worker_id,
                attempts=OutboxMessageModel.attempts + 1,
            )
            .returning(OutboxMessageModel)
        )
        return [to_domain(row) for row in result.all()]

    async def mark_processed(self, message_id: UUID, worker_id: UUID) -> None:
        """Помечает своё захваченное сообщение как успешно опубликованное.

        Условное обновление гарантирует, что помечает только воркер-владелец
        (``claimed_by``), и не трогает строки, уже снятые по lease.
        """
        await self._session.execute(
            update(OutboxMessageModel)
            .where(
                OutboxMessageModel.id == message_id,
                OutboxMessageModel.status == PROCESSING,
                OutboxMessageModel.claimed_by == worker_id,
            )
            .values(processed_at=func.now())
        )

    async def mark_publish_failure(
        self,
        message_id: UUID,
        *,
        worker_id: UUID,
        max_attempts: int,
        next_retry_at: datetime | None,
    ) -> None:
        """Возвращает своё сообщение в очередь или переводит в ``dead``.

        Если ``attempts`` ещё не достигли ``max_attempts``, сообщение становится
        ``pending`` с ``next_retry_at``; иначе — ``dead``. Lease снимается в обоих
        случаях. Решение по лимиту принимается по ``attempts`` в БД атомарно.
        """
        exceeded = OutboxMessageModel.attempts >= max_attempts
        next_retry = bindparam(
            'next_retry_at',
            value=next_retry_at,
            type_=DateTimeType(timezone=True),
        )
        await self._session.execute(
            update(OutboxMessageModel)
            .where(
                OutboxMessageModel.id == message_id,
                OutboxMessageModel.status == PROCESSING,
                OutboxMessageModel.claimed_by == worker_id,
            )
            .values(
                status=case((exceeded, DEAD), else_=PENDING),
                claimed_at=None,
                claimed_by=None,
                next_retry_at=case((exceeded, None), else_=next_retry),
            )
        )


__all__ = ['SqlAlchemyOutboxRepository']
