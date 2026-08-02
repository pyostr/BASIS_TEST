"""SQLAlchemy-репозиторий для доставок вебхуков (адаптер порта домена)."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.payments.domain.entities.webhook_delivery import (
    WebhookDelivery,
    WebhookDeliveryStatus,
)
from src.app.payments.infrastructure.mappers.webhook_delivery import to_domain, to_model
from src.app.payments.infrastructure.models.webhook_delivery import WebhookDeliveryModel


class SqlAlchemyWebhookDeliveryRepository:
    """SQLAlchemy-адаптер для порта домена репозитория доставок вебхуков."""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory

    @property
    def _session(self) -> AsyncSession:
        return self._session_factory()

    async def add(self, delivery: WebhookDelivery) -> None:
        """Помещает новую строку доставки в текущую сессию (ещё не зафлашена)."""
        self._session.add(to_model(delivery))

    async def get(self, delivery_id: UUID) -> WebhookDelivery | None:
        """Возвращает доставку по первичному ключу или None, если её нет."""
        row: WebhookDeliveryModel | None = await self._session.get(
            WebhookDeliveryModel, delivery_id
        )
        return to_domain(row) if row is not None else None

    async def claim_due(self, limit: int, now: datetime) -> list[WebhookDelivery]:
        """Забирает отложенные доставки, которые должны быть выполнены не позже ``now`` (SKIP LOCKED).

        Строки без next_retry_at считаются подлежащими немедленной доставке;
        FOR UPDATE SKIP LOCKED позволяет конкурентным воркерам делить работу без состязаний.
        """
        result = await self._session.execute(
            select(WebhookDeliveryModel)
            .where(
                WebhookDeliveryModel.status == WebhookDeliveryStatus.PENDING.value,
                or_(
                    WebhookDeliveryModel.next_retry_at.is_(None),
                    WebhookDeliveryModel.next_retry_at <= now,
                ),
            )
            .order_by(WebhookDeliveryModel.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [to_domain(row) for row in result.scalars()]

    async def update(self, delivery: WebhookDelivery) -> None:
        """Сохраняет прогресс доставки (attempt, status, ответ, время повтора)."""
        await self._session.execute(
            update(WebhookDeliveryModel)
            .where(WebhookDeliveryModel.id == delivery.id)
            .values(
                attempt=delivery.attempt,
                status=delivery.status.value,
                response_code=delivery.response_code,
                response_body=delivery.response_body,
                next_retry_at=delivery.next_retry_at,
                updated_at=delivery.updated_at,
            )
        )


__all__ = ['SqlAlchemyWebhookDeliveryRepository']
