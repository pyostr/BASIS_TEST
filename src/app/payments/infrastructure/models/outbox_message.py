"""SQLAlchemy-модель для транзакционной таблицы outbox."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.runtime.persistence.base import Base


class OutboxMessageModel(Base):
    """ORM-строка сохранённого доменного события, ожидающего публикации в брокер.

    ``processed_at`` отмечает успешную публикацию; индекс (processed_at, created_at)
    поддерживает запрос захвата воркером.
    """

    __tablename__ = 'outbox_messages'
    __table_args__ = (
        Index('ix_outbox_processed_created', 'processed_at', 'created_at'),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
