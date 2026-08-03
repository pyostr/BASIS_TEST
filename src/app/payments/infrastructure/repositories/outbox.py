"""SQLAlchemy-репозиторий для сообщений outbox (адаптер порта домена)."""

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import bindparam, case, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import DateTime as DateTimeType

from src.app.payments.domain.repositories.outbox import OutboxMessage
from src.app.payments.infrastructure.mappers.outbox import to_domain
from src.app.payments.infrastructure.models.outbox_message import OutboxMessageModel

PENDING = 'pending'
PROCESSING = 'processing'
PROCESSED = 'processed'
DEAD = 'dead'


class SqlAlchemyOutboxRepository:
    """SQLAlchemy-адаптер для порта домена репозитория outbox."""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory

    @property
    def _session(self) -> AsyncSession:
        return self._session_factory()

    async def release_expired_claims(
        self, now: datetime, timeout: int, max_attempts: int
    ) -> tuple[int, int]:
        """Снимает просроченные lease и возвращает число освобождённых сообщений.

        Упавший воркер (claim без mark) блокирует сообщение не дольше, чем на
        ``timeout`` секунд. Захваты, уже исчерпавшие лимит попыток
        (``attempts >= max_attempts``), не возвращаются в очередь, а сразу
        переводятся в ``dead``: иначе следующий claim увеличил бы ``attempts``
        сверх ``OUTBOX_MAX_ATTEMPTS``. Возвращает ``(released_dead,
        released_pending)``.
        """
        cutoff = now - timedelta(seconds=timeout)
        expired = (
            OutboxMessageModel.status == PROCESSING,
            OutboxMessageModel.claimed_at.is_not(None),
            OutboxMessageModel.claimed_at < cutoff,
        )
        result = await self._session.execute(
            update(OutboxMessageModel)
            .where(*expired, OutboxMessageModel.attempts >= max_attempts)
            .values(
                status=DEAD,
                claimed_at=None,
                claimed_by=None,
                next_retry_at=None,
                finished_at=func.now(),
            )
        )
        released_dead = result.rowcount or 0

        result = await self._session.execute(
            update(OutboxMessageModel)
            .where(*expired, OutboxMessageModel.attempts < max_attempts)
            .values(status=PENDING, claimed_at=None, claimed_by=None)
        )
        released_pending = result.rowcount or 0
        return released_dead, released_pending

    async def claim_batch(
        self,
        limit: int,
        now: datetime,
        worker_id: UUID,
        max_attempts: int,
    ) -> list[OutboxMessage]:
        """Атомарно захватывает до ``limit`` активных сообщений.

        Подзапрос выбирает ``pending``-сообщения с наступившим ``next_retry_at``
        и ещё не исчерпанным лимитом попыток (``attempts < max_attempts``) и
        блокирует их ``FOR UPDATE SKIP LOCKED`` (конкурентные воркеры получают
        непересекающиеся пакеты), затем единственное ``UPDATE`` переводит их в
        ``processing`` с владельцем, отметкой времени и инкрементом ``attempts``.
        """
        subquery = (
            select(OutboxMessageModel.id)
            .where(
                OutboxMessageModel.status == PENDING,
                OutboxMessageModel.processed_at.is_(None),
                OutboxMessageModel.attempts < max_attempts,
                or_(
                    OutboxMessageModel.next_retry_at.is_(None),
                    OutboxMessageModel.next_retry_at <= now,
                ),
            )
            .order_by(OutboxMessageModel.created_at, OutboxMessageModel.id)
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
        (``claimed_by``), и не трогает строки, уже снятые по lease. Сообщение
        переводится в терминальный статус ``processed``, а lease снимается.
        """
        await self._session.execute(
            update(OutboxMessageModel)
            .where(
                OutboxMessageModel.id == message_id,
                OutboxMessageModel.status == PROCESSING,
                OutboxMessageModel.claimed_by == worker_id,
            )
            .values(
                processed_at=func.now(),
                status=PROCESSED,
                claimed_at=None,
                claimed_by=None,
                finished_at=func.now(),
            )
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

        ``claim_batch`` уже увеличил ``attempts``, поэтому текущая неудачная
        попытка учитывается значением колонки: при ``attempts >= max_attempts``
        сообщение сразу становится ``dead`` (``finished_at`` фиксируется),
        иначе — ``pending`` с ``next_retry_at``. Lease снимается в обоих
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
                finished_at=case((exceeded, func.now()), else_=None),
            )
        )

    async def reap_exhausted(self, max_attempts: int) -> None:
        """Переводит в ``dead`` зависшие ``pending``-строки с исчерпанными попытками.

        Страховка для случаев, когда ``OUTBOX_MAX_ATTEMPTS`` уменьшили в рантайме
        или строка была восстановлена из бэкапа: такие сообщения никогда не
        должны захватываться вновь.
        """
        await self._session.execute(
            update(OutboxMessageModel)
            .where(
                OutboxMessageModel.status == PENDING,
                OutboxMessageModel.attempts >= max_attempts,
            )
            .values(
                status=DEAD,
                next_retry_at=None,
                finished_at=func.now(),
            )
        )

    async def purge_processed(self, cutoff: datetime) -> None:
        """Удаляет терминальные сообщения (``processed``/``dead``), завершённые раньше ``cutoff``.

        Retention: защищает таблицу outbox от неограниченного роста.
        """
        await self._session.execute(
            delete(OutboxMessageModel).where(
                OutboxMessageModel.status.in_((PROCESSED, DEAD)),
                OutboxMessageModel.finished_at.is_not(None),
                OutboxMessageModel.finished_at < cutoff,
            )
        )


__all__ = ['SqlAlchemyOutboxRepository']
