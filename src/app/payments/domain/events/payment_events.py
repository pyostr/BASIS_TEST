"""Конкретные доменные события, порождаемые агрегатом Payment, и их реестр."""

from dataclasses import dataclass
from datetime import datetime

from src.app.payments.domain.events.base import DomainEvent


@dataclass(frozen=True, kw_only=True)
class PaymentCreated(DomainEvent):
    """Порождается при создании платежа и содержит полные входные данные."""

    amount: str
    currency: str
    description: str | None
    metadata: dict
    webhook_url: str
    idempotency_key: str
    created_at: datetime


@dataclass(frozen=True, kw_only=True)
class PaymentProcessingStarted(DomainEvent):
    """Порождается при переходе платежа из pending в processing."""

    pass


@dataclass(frozen=True, kw_only=True)
class PaymentSucceeded(DomainEvent):
    """Порождается при успешном завершении платежа."""

    processed_at: datetime


@dataclass(frozen=True, kw_only=True)
class PaymentFailed(DomainEvent):
    """Порождается при неудаче платежа, с причиной неудачи."""

    reason: str | None
    processed_at: datetime


EVENT_TYPES: dict[str, type[DomainEvent]] = {
    'PaymentCreated': PaymentCreated,
    'PaymentProcessingStarted': PaymentProcessingStarted,
    'PaymentSucceeded': PaymentSucceeded,
    'PaymentFailed': PaymentFailed,
}
