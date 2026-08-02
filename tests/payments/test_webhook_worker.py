"""Тесты воркера доставки вебхуков: успешная доставка, повтор с отложенной
задержкой (backoff) и окончательная неудача после исчерпания попыток."""

from datetime import timedelta

from tests.payments.fakes import FakeClock, FakeWebhookClient
from tests.payments.helpers import NOW, build_payment, insert_payment

from src.app.payments.application.handlers.deliver_webhooks import (
    DeliverDueWebhooksHandler,
)
from src.app.payments.domain.entities.webhook_delivery import WebhookDelivery
from src.app.payments.domain.value_objects.retry_policy import RetryPolicy
from src.app.payments.infrastructure.uow import SqlAlchemyPaymentsUnitOfWork
from src.app.payments.infrastructure.webhook.worker import WebhookWorker
from src.config.settings import Settings
from src.shared.utils.uuid import uuid7


async def _setup_delivery(sessionmaker):
    """Сохраняет платёж с ожидающей доставкой вебхука и возвращает оба объекта."""
    payment = build_payment()
    await insert_payment(sessionmaker, payment)
    delivery = WebhookDelivery.create(
        id=uuid7(),
        payment_id=payment.id,
        event_type='payment.succeeded',
        correlation_id='corr-1',
        created_at=NOW,
    )
    async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
        await uow.webhook_delivery_repository.add(delivery)
        await uow.commit()
    return payment, delivery


def _worker(sessionmaker, client_responses, clock=None):
    """Создаёт WebhookWorker с реальными настройками и фейковыми клиентом/часами."""
    settings = Settings()
    deliver_handler = DeliverDueWebhooksHandler(
        lambda: SqlAlchemyPaymentsUnitOfWork(sessionmaker),
        FakeWebhookClient(client_responses),
        clock or FakeClock(),
        batch_size=settings.OUTBOX_BATCH_SIZE,
        retry_policy=RetryPolicy(
            max_attempts=settings.WEBHOOK_RETRY_ATTEMPTS,
            base_delay=settings.WEBHOOK_RETRY_BASE_DELAY,
        ),
    )
    return WebhookWorker(deliver_handler, poll_interval=settings.WEBHOOK_POLL_INTERVAL)


class TestWebhookWorker:
    """Сценарии webhook-воркера: успешная доставка, повторы, планирование backoff и окончательная неудача."""

    async def test_success_first_attempt(self, sessionmaker):
        """Ответ 2xx помечает доставку успешной с первой попытки."""
        _, delivery = await _setup_delivery(sessionmaker)
        worker = _worker(sessionmaker, [(200, '{}')])

        await worker.process_once()

        async with sessionmaker() as session:
            from sqlalchemy import text

            result = await session.execute(
                text(
                    'SELECT status, response_code FROM webhook_deliveries '
                    'WHERE id = :id'
                ),
                {'id': delivery.id},
            )
            status, response_code = result.one()

        assert status == 'success'
        assert response_code == 200

    async def test_retry_1_to_3_then_failed(self, sessionmaker):
        """Три подряд ответа 5xx исчерпывают попытки и помечают доставку неудачной."""
        payment, delivery = await _setup_delivery(sessionmaker)
        clock = FakeClock()
        worker = _worker(
            sessionmaker,
            [(500, 'boom'), (500, 'boom'), (500, 'boom')],
            clock=clock,
        )

        await worker.process_once()
        clock.advance(seconds=2)
        await worker.process_once()
        clock.advance(seconds=2)
        await worker.process_once()

        async with sessionmaker() as session:
            from sqlalchemy import text

            result = await session.execute(
                text(
                    'SELECT status, attempt, response_code FROM webhook_deliveries '
                    'WHERE id = :id'
                ),
                {'id': delivery.id},
            )
            status, attempt, response_code = result.one()

        assert status == 'failed'
        assert attempt == 3
        assert response_code == 500

    async def test_retry_backoff_schedules_next_attempt(self, sessionmaker):
        """Неудачная попытка остаётся в pending, увеличивает счётчик попыток и планирует повтор с backoff."""
        _, delivery = await _setup_delivery(sessionmaker)
        clock = FakeClock(start=NOW)
        worker = _worker(sessionmaker, [(500, 'boom')], clock=clock)

        await worker.process_once()

        async with sessionmaker() as session:
            from sqlalchemy import text

            result = await session.execute(
                text(
                    'SELECT status, attempt, next_retry_at FROM webhook_deliveries '
                    'WHERE id = :id'
                ),
                {'id': delivery.id},
            )
            status, attempt, next_retry_at = result.one()

        assert status == 'pending'
        assert attempt == 2
        assert next_retry_at == NOW.replace(microsecond=0) + timedelta(seconds=1)
