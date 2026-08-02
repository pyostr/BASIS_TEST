"""Порт персистентности для сущностей WebhookDelivery."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from src.app.payments.domain.entities.webhook_delivery import WebhookDelivery


class WebhookDeliveryRepository(Protocol):
    """Контракт персистентности для сущностей WebhookDelivery.

    Реализации должны поддерживать захват партий доставок, срок которых
    наступил, чтобы вебхук-воркер обрабатывал их без дубликатов.
    """

    async def add(self, delivery: WebhookDelivery) -> None:
        """Сохранить вновь созданную доставку."""

    async def get(self, delivery_id: UUID) -> WebhookDelivery | None:
        """Загрузить доставку по идентификатору или вернуть None."""

    async def claim_due(self, limit: int, now: datetime) -> list[WebhookDelivery]:
        """Захватить ожидающие доставки, готовые к повтору (FOR UPDATE SKIP LOCKED)."""
        ...

    async def update(self, delivery: WebhookDelivery) -> None:
        """Сохранить изменения существующей доставки."""
