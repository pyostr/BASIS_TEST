"""Адаптер единицы работы на основе SQLAlchemy для домена платежей.

Ограничивает репозитории одной сессией/транзакцией, обеспечивает семантику
commit/rollback и помещает собранные доменные события в таблицу outbox.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.app.payments.domain.events.base import DomainEvent
from src.app.payments.infrastructure.models.outbox_message import OutboxMessageModel
from src.app.payments.infrastructure.outbox.serialization import serialize_event
from src.app.payments.infrastructure.repositories.attempt import (
    SqlAlchemyAttemptRepository,
)
from src.app.payments.infrastructure.repositories.outbox import (
    SqlAlchemyOutboxRepository,
)
from src.app.payments.infrastructure.repositories.payment import (
    SqlAlchemyPaymentRepository,
)
from src.app.payments.infrastructure.repositories.webhook_delivery import (
    SqlAlchemyWebhookDeliveryRepository,
)
from src.shared.utils.uuid import uuid7


class SqlAlchemyPaymentsUnitOfWork:
    """Асинхронный контекстный менеджер, привязывающий репозитории к одной сессии SQLAlchemy.

    При выходе с исключением транзакция откатывается; в противном случае
    вызывающий код должен явно вызвать ``commit()``.
    """

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]):
        self._sessionmaker = sessionmaker
        self.session: AsyncSession | None = None
        self._committed = False
        self._rolled_back = False
        self.collected_events: list[DomainEvent] = []
        self.payment_repository = SqlAlchemyPaymentRepository(self._session_provider)
        self.attempt_repository = SqlAlchemyAttemptRepository(self._session_provider)
        self.outbox_repository = SqlAlchemyOutboxRepository(self._session_provider)
        self.webhook_delivery_repository = SqlAlchemyWebhookDeliveryRepository(
            self._session_provider
        )

    def _session_provider(self) -> AsyncSession:
        if self.session is None:
            raise RuntimeError('UnitOfWork session is not started')
        return self.session

    async def __aenter__(self) -> 'SqlAlchemyPaymentsUnitOfWork':
        """Открывает новую сессию и сбрасывает состояние commit/rollback."""
        self.session = self._sessionmaker()
        self._committed = False
        self._rolled_back = False
        self.collected_events = []
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Откатывает транзакцию при необработанных исключениях, затем всегда закрывает сессию."""
        try:
            if exc_type is not None and not self._committed and not self._rolled_back:
                await self.rollback()
        finally:
            if self.session is not None:
                await self.session.close()
                self.session = None

    async def commit(self) -> None:
        """Фиксирует текущую транзакцию и помечает единицу работы как закоммиченную."""
        if self.session is None:
            raise RuntimeError('UnitOfWork session is not started')
        await self.session.commit()
        self._committed = True

    async def rollback(self) -> None:
        """Откатывает текущую транзакцию (идемпотентно)."""
        if self.session is None or self._rolled_back:
            return
        await self.session.rollback()
        self._rolled_back = True

    async def collect_events(self, events: list[DomainEvent]) -> None:
        """Помещает доменные события как строки outbox в текущей транзакции."""
        if self.session is None:
            raise RuntimeError('UnitOfWork session is not started')

        for event in events:
            self.collected_events.append(event)
            self.session.add(
                OutboxMessageModel(
                    id=uuid7(),
                    event_type=type(event).__name__,
                    aggregate_id=event.aggregate_id,
                    payload=serialize_event(event),
                    correlation_id=event.correlation_id,
                    attempts=0,
                    created_at=event.occurred_at,
                    processed_at=None,
                )
            )


__all__ = ['SqlAlchemyPaymentsUnitOfWork']
