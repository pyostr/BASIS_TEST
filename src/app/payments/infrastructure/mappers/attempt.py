"""Маппер попыток платежей: инфраструктурная модель <-> доменная сущность."""

from src.app.payments.domain.entities.attempt import (
    PaymentAttempt,
    PaymentAttemptStatus,
)
from src.app.payments.infrastructure.models.payment_attempt import PaymentAttemptModel


def to_domain(row: PaymentAttemptModel) -> PaymentAttempt:
    """Преобразует строку PaymentAttemptModel в доменную сущность PaymentAttempt."""
    return PaymentAttempt(
        id=row.id,
        payment_id=row.payment_id,
        attempt_number=row.attempt_number,
        status=PaymentAttemptStatus(row.status),
        error=row.error,
        gateway_response=row.gateway_response,
        correlation_id=row.correlation_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


__all__ = ['to_domain']
