"""Хелперы для создания платёжных агрегатов и outbox-полезной нагрузки, общие для всех тестов payments."""

from datetime import UTC, datetime

from src.app.payments.domain.aggregates.payment import Payment
from src.app.payments.domain.events.payment_events import PaymentCreated
from src.app.payments.domain.value_objects.idempotency_key import IdempotencyKey
from src.app.payments.domain.value_objects.money import Currency, Money
from src.app.payments.infrastructure.outbox.serialization import serialize_event
from src.app.payments.infrastructure.uow import SqlAlchemyPaymentsUnitOfWork
from src.shared.utils.uuid import uuid7

NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)


def build_payment(idempotency_key: str = 'key-1', **overrides) -> Payment:
    """Создаёт агрегат Payment в статусе pending из корректных данных по умолчанию; переопределения применяются по ключу."""
    defaults = dict(
        id=uuid7(),
        idempotency_key=IdempotencyKey(idempotency_key),
        money=Money('100.00', Currency.RUB),
        description='test',
        metadata={},
        webhook_url='https://example.com/hook',
        correlation_id='corr-1',
        created_at=NOW,
    )
    defaults.update(overrides)
    return Payment.create(**defaults)


async def insert_payment(sessionmaker, payment: Payment) -> None:
    """Сохраняет платёж через реальный репозиторий и единицу работы."""
    async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
        await uow.payment_repository.try_insert(payment)
        await uow.commit()


def payment_created_payload(payment: Payment) -> dict:
    """Сериализует outbox-событие PaymentCreated для заданного платежа."""
    return serialize_event(
        PaymentCreated(
            aggregate_id=payment.id,
            occurred_at=NOW,
            correlation_id=payment.correlation_id,
            amount=str(payment.money.amount),
            currency=payment.money.currency.value,
            description=payment.description,
            metadata=payment.metadata,
            webhook_url=payment.webhook_url,
            idempotency_key=str(payment.idempotency_key),
            created_at=payment.created_at,
        )
    )
