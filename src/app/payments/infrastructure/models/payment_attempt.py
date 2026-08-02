"""SQLAlchemy-модель для таблицы попыток платежей."""

from datetime import datetime
from typing import Any
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.runtime.persistence.base import Base


class PaymentAttemptModel(Base):
    """ORM-строка одной попытки списания через шлюз по платежу.

    Связана с родительским платежом внешним ключом с каскадным удалением;
    индекс (payment_id, attempt_number) поддерживает выборки истории платежа.
    """

    __tablename__ = 'payment_attempts'
    __table_args__ = (
        CheckConstraint('attempt_number > 0', name='ck_attempts_number'),
        CheckConstraint(
            "status IN ('created', 'processing', 'succeeded', 'failed')",
            name='ck_attempts_status',
        ),
        Index('ix_attempts_payment_id_number', 'payment_id', 'attempt_number'),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    payment_id: Mapped[UUID] = mapped_column(
        ForeignKey('payments.id', ondelete='CASCADE'), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    gateway_response: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
