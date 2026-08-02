"""Базовый класс для всех доменных событий платежей."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Неизменяемые метаданные события: породивший агрегат, метка времени и correlation id."""

    aggregate_id: UUID
    occurred_at: datetime
    correlation_id: str | None = None
