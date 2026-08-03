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

    ``status`` переходит из ``pending`` в ``processing`` при захвате воркером
    (lease: claimed_at/claimed_by), а после исчерпания OUTBOX_MAX_ATTEMPTS — в
    ``dead``. ``next_retry_at`` откладывает повторный захват (экспоненциальный
    backoff); ``processed_at`` отмечает успешную публикацию. Индекс
    (status, next_retry_at, claimed_at) поддерживает запрос захвата воркером.
    """

    __tablename__ = 'outbox_messages'
    __table_args__ = (
        Index('idx_outbox_claim', 'status', 'next_retry_at', 'claimed_at'),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default='pending', server_default='pending'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    claimed_by: Mapped[UUID | None] = mapped_column(nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
