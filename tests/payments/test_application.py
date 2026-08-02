"""Тесты прикладного уровня для обработчиков create-payment и get-payment."""

from decimal import Decimal

import pytest
from sqlalchemy import text
from tests.payments.fakes import FakeClock

from src.app.payments.application.commands.create_payment import CreatePaymentCommand
from src.app.payments.application.handlers.create_payment import CreatePaymentHandler
from src.app.payments.application.handlers.get_payment import GetPaymentHandler
from src.app.payments.application.queries.get_payment import GetPaymentQuery
from src.app.payments.domain.aggregates.payment import PaymentStatus
from src.app.payments.domain.exceptions.payment_exceptions import (
    InvalidPaymentData,
    PaymentNotFound,
)
from src.app.payments.infrastructure.uow import SqlAlchemyPaymentsUnitOfWork
from src.shared.utils.uuid import uuid7


def make_command(**overrides) -> CreatePaymentCommand:
    """Создаёт CreatePaymentCommand из корректных данных по умолчанию; переопределения применяются по ключу."""
    defaults = dict(
        idempotency_key='client-ref-1',
        amount=Decimal('150.00'),
        currency='RUB',
        description='order #1',
        metadata={'user': 42},
        webhook_url='https://example.com/hook',
        correlation_id='corr-1',
    )
    defaults.update(overrides)
    return CreatePaymentCommand(**defaults)


async def _count(sessionmaker, table: str) -> int:
    """Возвращает количество строк в указанной таблице."""
    async with sessionmaker() as session:
        result = await session.execute(text(f'SELECT count(*) FROM {table}'))
        return result.scalar_one()


@pytest.fixture
def uow_factory(sessionmaker):
    """Фикстура, возвращающая фабрику UoW, привязанную к тестовому sessionmaker."""
    return lambda: SqlAlchemyPaymentsUnitOfWork(sessionmaker)


class TestCreatePaymentHandler:
    """Сценарии для CreatePaymentHandler: сохранение, outbox-события, идемпотентность, валидация."""

    async def test_create_payment(self, uow_factory, sessionmaker):
        """Создание платежа сохраняет его и outbox-событие PaymentCreated, без попыток."""
        handler = CreatePaymentHandler(uow_factory, FakeClock())
        dto = await handler.handle(make_command())

        assert dto.payment_id
        assert dto.status == PaymentStatus.PENDING.value
        assert dto.amount == Decimal('150.00')
        assert dto.currency == 'RUB'
        assert dto.idempotency_key == 'client-ref-1'
        assert dto.attempts is None

        assert await _count(sessionmaker, 'payments') == 1
        assert await _count(sessionmaker, 'outbox_messages') == 1
        assert await _count(sessionmaker, 'payment_attempts') == 0

    async def test_create_payment_stores_outbox_event(self, uow_factory, sessionmaker):
        """Outbox-сообщение хранит тип события PaymentCreated вместе с correlation id."""
        await CreatePaymentHandler(uow_factory, FakeClock()).handle(make_command())

        async with sessionmaker() as session:
            result = await session.execute(
                text('SELECT event_type, correlation_id FROM outbox_messages')
            )
            row = result.one()

        assert row.event_type == 'PaymentCreated'
        assert row.correlation_id == 'corr-1'

    async def test_repeated_key_returns_existing(self, uow_factory, sessionmaker):
        """Повтор того же idempotency-ключа возвращает существующий платёж без лишних строк."""
        handler = CreatePaymentHandler(uow_factory, FakeClock())
        first = await handler.handle(make_command())
        second = await handler.handle(make_command())

        assert second.payment_id == first.payment_id
        assert await _count(sessionmaker, 'payments') == 1
        assert await _count(sessionmaker, 'outbox_messages') == 1

    async def test_different_keys_create_two_payments(self, uow_factory, sessionmaker):
        """Разные idempotency-ключи создают разные платежи."""
        handler = CreatePaymentHandler(uow_factory, FakeClock())
        await handler.handle(make_command(idempotency_key='key-1'))
        await handler.handle(make_command(idempotency_key='key-2'))

        assert await _count(sessionmaker, 'payments') == 2

    async def test_invalid_amount_rejected(self, uow_factory):
        """Отрицательная сумма вызывает InvalidPaymentData."""
        handler = CreatePaymentHandler(uow_factory, FakeClock())
        with pytest.raises(InvalidPaymentData):
            await handler.handle(make_command(amount=Decimal('-5')))

    async def test_invalid_currency_rejected(self, uow_factory):
        """Неподдерживаемая валюта вызывает InvalidPaymentData."""
        handler = CreatePaymentHandler(uow_factory, FakeClock())
        with pytest.raises(InvalidPaymentData):
            await handler.handle(make_command(currency='GBP'))


class TestGetPaymentHandler:
    """Сценарии для GetPaymentHandler: получение созданного и отсутствующего платежа."""

    async def test_get_payment(self, uow_factory, sessionmaker):
        """Созданный платёж возвращается со статусом pending и пустым списком попыток."""
        created = await CreatePaymentHandler(uow_factory, FakeClock()).handle(
            make_command()
        )

        dto = await GetPaymentHandler(uow_factory).handle(
            GetPaymentQuery(payment_id=created.payment_id)
        )

        assert dto.payment_id == created.payment_id
        assert dto.status == PaymentStatus.PENDING.value
        assert dto.attempts == []

    async def test_get_missing_payment(self, uow_factory):
        """Запрос по неизвестному id платежа вызывает PaymentNotFound."""
        with pytest.raises(PaymentNotFound):
            await GetPaymentHandler(uow_factory).handle(
                GetPaymentQuery(payment_id=uuid7())
            )
