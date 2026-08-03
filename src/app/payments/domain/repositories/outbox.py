"""Модель сообщения Outbox и порт его персистентности."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


@dataclass
class OutboxMessage:
    """Строка Outbox: сохранённое доменное событие, ожидающее публикации."""

    id: UUID
    event_type: str
    aggregate_id: UUID
    payload: dict[str, Any]
    correlation_id: str | None
    attempts: int
    status: str
    created_at: datetime
    next_retry_at: datetime | None
    claimed_at: datetime | None
    claimed_by: UUID | None
    processed_at: datetime | None


class OutboxRepository(Protocol):
    """Контракт персистентности для сообщений outbox.

    Захват (claim) атомарно переводит сообщение в статус ``processing`` и
    помечает его владельца (``claimed_by``); результаты публикации фиксируются
    условными обновлениями, чтобы другой воркер не мог пометить чужое сообщение.
    """

    async def release_expired_claims(
        self, now: datetime, timeout: int, max_attempts: int
    ) -> tuple[int, int]:
        """Снять просроченные захваты.

        Захват считается просроченным, если ``claimed_at`` старше
        ``now - timeout`` секунд; lease снимается, чтобы упавший воркер не
        блокировал сообщение навсегда. Сообщения с ``attempts >= max_attempts``
        переводятся в ``dead``, остальные возвращаются в ``pending``. Возвращает
        ``(released_dead, released_pending)``.
        """
        ...

    async def claim_batch(
        self,
        limit: int,
        now: datetime,
        worker_id: UUID,
        max_attempts: int,
    ) -> list[OutboxMessage]:
        """Атомарно захватить до ``limit`` активных сообщений.

        Выбирает ``pending``-сообщения, чей ``next_retry_at`` наступил и чей
        ``attempts`` ещё меньше ``max_attempts``, переводит их в ``processing``
        с ``claimed_by`` и инкрементом ``attempts``.
        """
        ...

    async def mark_processed(self, message_id: UUID, worker_id: UUID) -> None:
        """Пометить своё захваченное сообщение как успешно опубликованное
        (переход в терминальный статус ``processed``)."""

    async def mark_publish_failure(
        self,
        message_id: UUID,
        *,
        worker_id: UUID,
        max_attempts: int,
        next_retry_at: datetime | None,
    ) -> None:
        """Вернуть своё сообщение в очередь или перевести в ``dead``.

        Если ``attempts`` (после инкремента в ``claim_batch``) не достигли
        ``max_attempts``, сообщение возвращается в ``pending`` с
        ``next_retry_at``; иначе переводится в ``dead``.
        """

    async def reap_exhausted(self, max_attempts: int) -> None:
        """Перевести зависшие ``pending``-строки с ``attempts >= max_attempts`` в ``dead``."""

    async def purge_processed(self, cutoff: datetime) -> None:
        """Удалить терминальные строки, завершённые раньше ``cutoff`` (retention)."""
