"""Порт UnitOfWork: транзакционная граница для всех репозиториев платежей."""

from typing import Protocol

from src.app.payments.domain.events.base import DomainEvent
from src.app.payments.domain.repositories.attempt import AttemptRepository
from src.app.payments.domain.repositories.outbox import OutboxRepository
from src.app.payments.domain.repositories.payment import PaymentRepository
from src.app.payments.domain.repositories.webhook_delivery import (
    WebhookDeliveryRepository,
)


class UnitOfWork(Protocol):
    """Транзакционная граница, предоставляющая все репозитории платежей.

    Контракт: вход в контекст открывает транзакцию, commit() атомарно
    сохраняет все изменения, а rollback() их отменяет. collected_events
    буферизует доменные события для публикации в outbox при коммите.
    """

    payment_repository: PaymentRepository
    attempt_repository: AttemptRepository
    outbox_repository: OutboxRepository
    webhook_delivery_repository: WebhookDeliveryRepository

    collected_events: list[DomainEvent]

    async def __aenter__(self) -> 'UnitOfWork':
        """Открыть транзакцию и вернуть единицу работы."""

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Закрыть транзакцию с откатом, если она ещё не была закоммичена."""

    async def commit(self) -> None:
        """Атомарно сохранить все накопленные изменения."""

    async def rollback(self) -> None:
        """Отменить все накопленные изменения."""

    async def collect_events(self, events: list[DomainEvent]) -> None:
        """Буферизовать доменные события для сохранения в outbox при коммите."""


class UnitOfWorkFactory(Protocol):
    """Фабрика единиц работы: возвращает новый UoW на каждый вызов."""

    def __call__(self) -> UnitOfWork: ...
