"""Объекты передачи данных, предоставляющие состояние агрегата платежа прикладному слою."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from src.app.payments.domain.aggregates.payment import Payment
from src.app.payments.domain.entities.attempt import PaymentAttempt


@dataclass
class AttemptDTO:
    """Проекция PaymentAttempt только для чтения для ответов API."""

    attempt_number: int
    status: str
    error: str | None
    gateway_response: dict[str, Any] | None
    created_at: datetime

    @classmethod
    def from_attempt(cls, attempt: PaymentAttempt) -> 'AttemptDTO':
        """Собрать AttemptDTO из доменного PaymentAttempt."""
        return cls(
            attempt_number=attempt.attempt_number,
            status=attempt.status.value,
            error=attempt.error,
            gateway_response=attempt.gateway_response,
            created_at=attempt.created_at,
        )


@dataclass
class PaymentDTO:
    """Проекция агрегата Payment только для чтения, при необходимости с попытками."""

    payment_id: UUID
    status: str
    amount: Decimal
    currency: str
    description: str | None
    metadata: dict[str, Any]
    idempotency_key: str
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None
    attempts: list[AttemptDTO] | None = None

    @classmethod
    def from_payment(
        cls,
        payment: Payment,
        attempts: list[PaymentAttempt] | None = None,
    ) -> 'PaymentDTO':
        """Собрать PaymentDTO из агрегата Payment; включать попытки, если они переданы."""
        return cls(
            payment_id=payment.id,
            status=payment.status.value,
            amount=payment.money.amount,
            currency=payment.money.currency.value,
            description=payment.description,
            metadata=payment.metadata,
            idempotency_key=str(payment.idempotency_key),
            webhook_url=payment.webhook_url,
            created_at=payment.created_at,
            processed_at=payment.processed_at,
            attempts=(
                [AttemptDTO.from_attempt(a) for a in attempts]
                if attempts is not None
                else None
            ),
        )
