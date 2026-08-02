"""Композиционный контейнер платежей, предоставляющий обработчики и фабрику UoW."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.app.payments.application.handlers.create_payment import CreatePaymentHandler
from src.app.payments.application.handlers.get_payment import GetPaymentHandler
from src.app.payments.infrastructure.uow import SqlAlchemyPaymentsUnitOfWork
from src.shared.domain.clock import Clock
from src.shared.utils.clock import SystemClock


@dataclass
class PaymentsContainer:
    """Хранит инфраструктуру платежей и собирает обработчики приложения поверх общей фабрики UoW."""

    sessionmaker: async_sessionmaker[AsyncSession]
    clock: Clock | None = None

    def __post_init__(self) -> None:
        if self.clock is None:
            self.clock = SystemClock()

    @property
    def uow_factory(self):
        """Возвращает фабрику, создающую новый Unit of Work платежей при каждом вызове."""
        return lambda: SqlAlchemyPaymentsUnitOfWork(self.sessionmaker)

    def create_payment_handler(self) -> CreatePaymentHandler:
        """Собирает use case создания платежа, связанный с UoW и часами этого контейнера."""
        return CreatePaymentHandler(uow_factory=self.uow_factory, clock=self.clock)

    def get_payment_handler(self) -> GetPaymentHandler:
        """Собирает use case получения платежа, связанный с UoW этого контейнера."""
        return GetPaymentHandler(uow_factory=self.uow_factory)
