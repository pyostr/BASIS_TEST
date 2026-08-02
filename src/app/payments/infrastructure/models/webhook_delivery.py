"""SQLAlchemy-модель для попыток доставки вебхуков."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.runtime.persistence.base import Base


class WebhookDeliveryModel(Base):
    """ORM-строка, отслеживающая попытки доставки вебхуков и планирование повторов.

    ``next_retry_at`` определяет, когда отложенная доставка становится доступной
    для следующей попытки; её индекс поддерживает запрос захвата воркером.
    """

    __tablename__ = 'webhook_deliveries'
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'success', 'failed')",
            name='ck_webhook_deliveries_status',
        ),
        Index('ix_webhook_deliveries_payment_event', 'payment_id', 'event_type'),
        Index('ix_webhook_deliveries_next_retry_at', 'next_retry_at'),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    payment_id: Mapped[UUID] = mapped_column(
        ForeignKey('payments.id', ondelete='CASCADE'), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
