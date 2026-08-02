"""Доменные события, порождаемые агрегатом платежей, и реестр EVENT_TYPES."""

from src.app.payments.domain.events.base import DomainEvent
from src.app.payments.domain.events.payment_events import (
    EVENT_TYPES,
    PaymentCreated,
    PaymentFailed,
    PaymentProcessingStarted,
    PaymentSucceeded,
)

__all__ = [
    'DomainEvent',
    'PaymentCreated',
    'PaymentProcessingStarted',
    'PaymentSucceeded',
    'PaymentFailed',
    'EVENT_TYPES',
]
