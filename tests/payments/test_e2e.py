"""Сквозные (E2E) тесты, прогоняющие весь платёжный конвейер через реальные Postgres
и RabbitMQ: публикация outbox, обработка consumer и доставка вебхуков."""

import asyncio

from faststream.rabbit import RabbitQueue
from tests.payments.fakes import FakeClock, FakeWebhookClient, ScriptedGateway
from tests.payments.test_application import make_command

from src.app.payments.application.handlers.create_payment import CreatePaymentHandler
from src.app.payments.application.handlers.deliver_webhooks import (
    DeliverDueWebhooksHandler,
)
from src.app.payments.application.handlers.process_payment import ProcessPaymentHandler
from src.app.payments.domain.aggregates.payment import PaymentStatus
from src.app.payments.domain.gateway import GatewayResult
from src.app.payments.domain.value_objects.retry_policy import RetryPolicy
from src.app.payments.infrastructure.broker.broker import (
    build_broker,
    declare_topology,
    register_consumer,
)
from src.app.payments.infrastructure.outbox.worker import OutboxWorker
from src.app.payments.infrastructure.repositories.payment import (
    SqlAlchemyPaymentRepository,
)
from src.app.payments.infrastructure.uow import SqlAlchemyPaymentsUnitOfWork
from src.app.payments.infrastructure.webhook.worker import WebhookWorker
from src.config.settings import Settings


class RaisingGateway:
    """Заменитель шлюза, который всегда бросает исключение, имитируя устойчивый сбой инфраструктуры."""

    def __init__(self) -> None:
        self.calls = 0

    async def charge(self, *args, **kwargs):
        self.calls += 1
        raise RuntimeError('gateway timeout')


def _amqp_url(container) -> str:
    """Строит AMQP URL, указывающий на тестовый RabbitMQ-контейнер."""
    host = container.get_container_host_ip()
    port = container.get_exposed_port(5672)
    return f'amqp://guest:guest@{host}:{port}/'


def _settings(container, suffix: str, **overrides) -> Settings:
    """Строит настройки с изолированной топологией очередей для каждого теста.

    Очереди в RabbitMQ durable и переживают перезапуск брокера, поэтому каждый
    тест должен использовать свои имена exchange/queue, чтобы оставшаяся топология
    (например, устаревший TTL) не мешала сценарию.
    """
    defaults = {
        'RABBITMQ_URL': _amqp_url(container),
        'RABBITMQ_EXCHANGE': f'payments.{suffix}.exchange',
        'RABBITMQ_ROUTING_KEY': f'payments.{suffix}.new',
        'RABBITMQ_QUEUE': f'payments.{suffix}.new',
        'RABBITMQ_RETRY_QUEUE': f'payments.{suffix}.retry',
        'RABBITMQ_DLQ_QUEUE': f'payments.{suffix}.dlq',
    }
    defaults.update(overrides)
    return Settings(**defaults)


async def _load_payment(sessionmaker, payment_id):
    """Перезагружает агрегат платежа из базы данных."""
    async with sessionmaker() as session:
        return await SqlAlchemyPaymentRepository(lambda: session).get(payment_id)


def _uow_factory(sessionmaker):
    """Возвращает фабрику UoW, привязанную к тестовому sessionmaker."""
    return lambda: SqlAlchemyPaymentsUnitOfWork(sessionmaker)


def _process_handler(sessionmaker, gateway, clock) -> ProcessPaymentHandler:
    """Создаёт ProcessPaymentHandler, подключённый к заданным шлюзу и часам."""
    return ProcessPaymentHandler(_uow_factory(sessionmaker), gateway, clock)


def _webhook_worker(sessionmaker, webhook_client, settings, clock) -> WebhookWorker:
    """Создаёт WebhookWorker с реальными настройками доставки и заданными клиентом/часами."""
    deliver = DeliverDueWebhooksHandler(
        _uow_factory(sessionmaker),
        webhook_client,
        clock,
        batch_size=settings.OUTBOX_BATCH_SIZE,
        retry_policy=RetryPolicy(
            max_attempts=settings.WEBHOOK_RETRY_ATTEMPTS,
            base_delay=settings.WEBHOOK_RETRY_BASE_DELAY,
        ),
    )
    return WebhookWorker(deliver, poll_interval=settings.WEBHOOK_POLL_INTERVAL)


async def _wait_for_terminal(sessionmaker, payment_id, timeout: float = 10.0):
    """Ожидает, пока платёж не достигнет терминального состояния, или бросает исключение по таймауту."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        payment = await _load_payment(sessionmaker, payment_id)
        if payment is not None and payment.status in (
            PaymentStatus.SUCCEEDED,
            PaymentStatus.FAILED,
        ):
            return payment
        await asyncio.sleep(0.05)
    raise AssertionError('payment did not reach a terminal state in time')


class TestEndToEnd:
    """Сценарии полного конвейера: успешное списание, распространение отказа и DLQ при сбоях инфраструктуры."""

    async def test_full_pipeline_success(self, rabbitmq_container, sessionmaker):
        """Успешно списанный платёж проходит сквозь весь конвейер, и его вебхук доставляется."""
        settings = _settings(rabbitmq_container, 'success')
        broker = build_broker(settings)
        clock = FakeClock()
        gateway = ScriptedGateway(
            [GatewayResult(success=True, gateway_id='gw-e2e', raw={'txn': 'e2e'})]
        )
        register_consumer(
            broker, _process_handler(sessionmaker, gateway, clock), settings
        )

        await broker.start()
        try:
            await declare_topology(broker, settings)

            dto = await CreatePaymentHandler(
                lambda: SqlAlchemyPaymentsUnitOfWork(sessionmaker), clock
            ).handle(make_command())

            outbox_worker = OutboxWorker(sessionmaker, broker, settings)
            await outbox_worker._publish_batch()

            payment = await _wait_for_terminal(sessionmaker, dto.payment_id)
            assert payment.status is PaymentStatus.SUCCEEDED
            assert gateway.calls == 1

            webhook_client = FakeWebhookClient([(200, '{}')])
            webhook_worker = _webhook_worker(
                sessionmaker, webhook_client, settings, clock
            )
            await webhook_worker.process_once()

            assert len(webhook_client.sent) == 1
            async with sessionmaker() as session:
                from sqlalchemy import text

                result = await session.execute(
                    text(
                        'SELECT status FROM webhook_deliveries WHERE payment_id = :id'
                    ),
                    {'id': dto.payment_id},
                )
                assert result.scalar_one() == 'success'
        finally:
            await broker.stop()

    async def test_gateway_decline_propagates_to_webhook(
        self, rabbitmq_container, sessionmaker
    ):
        """Отказ шлюза завершает платёж неудачей и доставляет вебхук payment.failed."""
        settings = _settings(rabbitmq_container, 'decline')
        broker = build_broker(settings)
        clock = FakeClock()
        gateway = ScriptedGateway([GatewayResult(success=False, error='declined')])
        register_consumer(
            broker, _process_handler(sessionmaker, gateway, clock), settings
        )

        await broker.start()
        try:
            await declare_topology(broker, settings)

            dto = await CreatePaymentHandler(
                lambda: SqlAlchemyPaymentsUnitOfWork(sessionmaker), clock
            ).handle(make_command())

            outbox_worker = OutboxWorker(sessionmaker, broker, settings)
            await outbox_worker._publish_batch()

            payment = await _wait_for_terminal(sessionmaker, dto.payment_id)
            assert payment.status is PaymentStatus.FAILED

            webhook_client = FakeWebhookClient([(200, '{}')])
            webhook_worker = _webhook_worker(
                sessionmaker, webhook_client, settings, clock
            )
            await webhook_worker.process_once()

            assert len(webhook_client.sent) == 1
            async with sessionmaker() as session:
                from sqlalchemy import text

                result = await session.execute(
                    text(
                        'SELECT event_type FROM webhook_deliveries '
                        'WHERE payment_id = :id'
                    ),
                    {'id': dto.payment_id},
                )
                assert result.scalar_one() == 'payment.failed'
        finally:
            await broker.stop()

    async def test_infrastructure_error_goes_to_dlq(
        self, rabbitmq_container, sessionmaker
    ):
        """Устойчивый сбой инфраструктуры приводит к повторам, а затем сообщение направляется в DLQ."""
        settings = _settings(
            rabbitmq_container,
            'dlq',
            RABBITMQ_RETRY_TTL_MS=100,
            RABBITMQ_MAX_RETRIES=3,
        )
        broker = build_broker(settings)
        clock = FakeClock()
        gateway = RaisingGateway()
        register_consumer(
            broker, _process_handler(sessionmaker, gateway, clock), settings
        )

        dlq_received = asyncio.Event()

        @broker.subscriber(RabbitQueue(name=settings.RABBITMQ_DLQ_QUEUE, durable=True))
        async def on_dlq(msg) -> None:
            dlq_received.set()

        await broker.start()
        try:
            await declare_topology(broker, settings)

            dto = await CreatePaymentHandler(
                lambda: SqlAlchemyPaymentsUnitOfWork(sessionmaker), clock
            ).handle(make_command())

            outbox_worker = OutboxWorker(sessionmaker, broker, settings)
            await outbox_worker._publish_batch()

            await asyncio.wait_for(dlq_received.wait(), timeout=15.0)

            loaded = await _load_payment(sessionmaker, dto.payment_id)
            assert loaded is not None
            assert loaded.status is PaymentStatus.PENDING
            assert gateway.calls == 3
        finally:
            await broker.stop()
