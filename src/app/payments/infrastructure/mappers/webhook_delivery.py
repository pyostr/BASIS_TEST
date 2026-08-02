"""Маппер доставок вебхуков: инфраструктурная модель <-> доменная сущность."""

from src.app.payments.domain.entities.webhook_delivery import (
    WebhookDelivery,
    WebhookDeliveryStatus,
)
from src.app.payments.infrastructure.models.webhook_delivery import WebhookDeliveryModel


def to_domain(row: WebhookDeliveryModel) -> WebhookDelivery:
    """Преобразует строку WebhookDeliveryModel в доменную сущность WebhookDelivery."""
    return WebhookDelivery(
        id=row.id,
        payment_id=row.payment_id,
        event_type=row.event_type,
        attempt=row.attempt,
        status=WebhookDeliveryStatus(row.status),
        response_code=row.response_code,
        response_body=row.response_body,
        next_retry_at=row.next_retry_at,
        correlation_id=row.correlation_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def to_model(delivery: WebhookDelivery) -> WebhookDeliveryModel:
    """Преобразует доменную сущность WebhookDelivery в строку модели."""
    return WebhookDeliveryModel(
        id=delivery.id,
        payment_id=delivery.payment_id,
        event_type=delivery.event_type,
        attempt=delivery.attempt,
        status=delivery.status.value,
        response_code=delivery.response_code,
        response_body=delivery.response_body,
        next_retry_at=delivery.next_retry_at,
        correlation_id=delivery.correlation_id,
        created_at=delivery.created_at,
        updated_at=delivery.updated_at,
    )


__all__ = ['to_domain', 'to_model']
