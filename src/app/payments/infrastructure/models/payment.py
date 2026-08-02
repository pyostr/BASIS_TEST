"""SQLAlchemy-модель для таблицы агрегата платежей."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.runtime.persistence.base import Base


class PaymentModel(Base):
    """ORM-строка корневого агрегата Payment.

    ``version`` — монотонный счётчик для оптимистичной блокировки, а
    ``idempotency_key`` уникален и поддерживает идемпотентные вставки.
    """

    __tablename__ = 'payments'
    __table_args__ = (
        CheckConstraint('amount > 0', name='ck_payments_amount_positive'),
        CheckConstraint(
            "currency IN ('RUB', 'USD', 'EUR')", name='ck_payments_currency'
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'succeeded', 'failed')",
            name='ck_payments_status',
        ),
        CheckConstraint("webhook_url ~ '^https?://'", name='ck_payments_webhook_url'),
        Index('ix_payments_status', 'status'),
        Index('ix_payments_created_at', 'created_at'),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column('metadata', JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')
    webhook_url: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
