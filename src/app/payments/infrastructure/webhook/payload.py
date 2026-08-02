"""Собирает JSON-тело payload, отправляемое на URL вебхуков."""

from src.app.payments.domain.aggregates.payment import Payment
from src.app.payments.domain.entities.webhook_delivery import WebhookDelivery


def build_webhook_payload(payment: Payment, delivery: WebhookDelivery) -> dict:
    """Собирает ориентированный на мерчанта payload вебхука в виде простого JSON-безопасного словаря."""
    return {
        'event': delivery.event_type,
        'payment_id': str(payment.id),
        'status': payment.status.value,
        'amount': str(payment.money.amount),
        'currency': payment.money.currency.value,
        'idempotency_key': str(payment.idempotency_key),
        'description': payment.description,
        'metadata': payment.metadata,
        'created_at': payment.created_at.isoformat(),
        'processed_at': (
            payment.processed_at.isoformat() if payment.processed_at else None
        ),
        'correlation_id': delivery.correlation_id,
    }


__all__ = ['build_webhook_payload']
