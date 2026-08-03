"""Маппер сообщений outbox: инфраструктурная модель <-> доменная сущность."""

from src.app.payments.domain.repositories.outbox import OutboxMessage
from src.app.payments.infrastructure.models.outbox_message import OutboxMessageModel


def to_domain(row: OutboxMessageModel) -> OutboxMessage:
    """Преобразует строку OutboxMessageModel в доменную сущность OutboxMessage."""
    return OutboxMessage(
        id=row.id,
        event_type=row.event_type,
        aggregate_id=row.aggregate_id,
        payload=row.payload,
        correlation_id=row.correlation_id,
        attempts=row.attempts,
        status=row.status,
        created_at=row.created_at,
        next_retry_at=row.next_retry_at,
        processed_at=row.processed_at,
    )


__all__ = ['to_domain']
