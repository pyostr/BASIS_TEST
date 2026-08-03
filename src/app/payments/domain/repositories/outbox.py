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
    processed_at: datetime | None


class OutboxRepository(Protocol):
    """Контракт персистентности для сообщений outbox.

    Реализации должны позволять захватывать партии ожидающих сообщений без
    их повторной обработки и атомарно фиксировать результаты публикации.
    """

    async def claim_batch(self, limit: int, now: datetime) -> list[OutboxMessage]:
        """Захватить ожидающие сообщения (FOR UPDATE SKIP LOCKED).

        Возвращает только активные сообщения, чей ``next_retry_at`` уже наступил.
        """
        ...

    async def mark_processed(self, message_id: UUID) -> None:
        """Пометить сообщение как успешно опубликованное."""

    async def mark_publish_failure(
        self,
        message_id: UUID,
        *,
        max_attempts: int,
        next_retry_at: datetime | None,
    ) -> None:
        """Увеличить счётчик попыток и отложить повторную публикацию.

        При достижении ``max_attempts`` переводит сообщение в статус ``dead``.
        """
