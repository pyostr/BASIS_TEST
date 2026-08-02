"""Маппер платежей: инфраструктурная модель <-> доменный агрегат."""

from src.app.payments.domain.aggregates.payment import Payment, PaymentStatus
from src.app.payments.domain.value_objects.idempotency_key import IdempotencyKey
from src.app.payments.domain.value_objects.money import Money
from src.app.payments.infrastructure.models.payment import PaymentModel


def to_domain(row: PaymentModel) -> Payment:
    """Преобразует строку PaymentModel в доменный агрегат Payment.

    Сырые скалярные колонки оборачиваются обратно в объекты-значения
    IdempotencyKey/Money и в enum статуса.
    """
    return Payment(
        id=row.id,
        idempotency_key=IdempotencyKey(row.idempotency_key),
        money=Money(row.amount, row.currency),
        description=row.description,
        metadata=row.metadata_,
        webhook_url=row.webhook_url,
        correlation_id=row.correlation_id,
        status=PaymentStatus(row.status),
        created_at=row.created_at,
        processed_at=row.processed_at,
        version=row.version,
    )


__all__ = ['to_domain']
