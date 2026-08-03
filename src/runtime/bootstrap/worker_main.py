"""Композиционный корень воркера: запуск асинхронных консьюмеров (брокер, outbox, вебхуки)."""

import asyncio
import logging

from prometheus_client import start_http_server

from src.app.payments.application.handlers.deliver_webhooks import (
    DeliverDueWebhooksHandler,
)
from src.app.payments.application.handlers.process_payment import ProcessPaymentHandler
from src.app.payments.domain.value_objects.retry_policy import RetryPolicy
from src.app.payments.infrastructure.broker.broker import (
    build_broker,
    declare_topology,
    register_consumer,
)
from src.app.payments.infrastructure.gateway.fake_gateway import FakeGateway
from src.app.payments.infrastructure.outbox.worker import OutboxWorker
from src.app.payments.infrastructure.uow import SqlAlchemyPaymentsUnitOfWork
from src.app.payments.infrastructure.webhook.client import WebhookClient
from src.app.payments.infrastructure.webhook.worker import WebhookWorker
from src.config.settings import get_settings
from src.runtime.logging.logger import setup_logging
from src.runtime.persistence.session import dispose_engine, get_engine, get_sessionmaker
from src.shared.utils.clock import SystemClock

logger = logging.getLogger(__name__)


async def main() -> None:
    """Связывает engine, брокер, воркеры outbox и вебхуков, затем запускает их до отмены."""
    settings = get_settings()
    setup_logging()

    start_http_server(settings.METRICS_PORT)
    logger.info('Metrics HTTP server started on port %s', settings.METRICS_PORT)

    await get_engine(settings)
    sessionmaker = await get_sessionmaker(settings)

    def uow_factory():
        """Создаёт новый Unit of Work платежей, привязанный к sessionmaker процесса."""
        return SqlAlchemyPaymentsUnitOfWork(sessionmaker)

    broker = build_broker(settings)
    clock = SystemClock()
    gateway = FakeGateway(
        min_delay=settings.GATEWAY_MIN_DELAY,
        max_delay=settings.GATEWAY_MAX_DELAY,
        failure_rate=settings.GATEWAY_FAILURE_RATE,
    )
    webhook_client = WebhookClient(
        secret=settings.WEBHOOK_SECRET,
        timeout=settings.WEBHOOK_TIMEOUT,
    )

    process_payment = ProcessPaymentHandler(
        uow_factory=uow_factory,
        gateway=gateway,
        clock=clock,
    )
    register_consumer(broker, process_payment, settings)

    await broker.start()
    await declare_topology(broker, settings)

    outbox_worker = OutboxWorker(
        sessionmaker=sessionmaker,
        broker=broker,
        settings=settings,
    )
    deliver_webhooks = DeliverDueWebhooksHandler(
        uow_factory=uow_factory,
        webhook_sender=webhook_client,
        clock=clock,
        batch_size=settings.OUTBOX_BATCH_SIZE,
        retry_policy=RetryPolicy(
            max_attempts=settings.WEBHOOK_RETRY_ATTEMPTS,
            base_delay=settings.WEBHOOK_RETRY_BASE_DELAY,
        ),
        concurrency=settings.WEBHOOK_CONCURRENCY,
    )
    webhook_worker = WebhookWorker(
        deliver_handler=deliver_webhooks,
        poll_interval=settings.WEBHOOK_POLL_INTERVAL,
    )

    logger.info('Payments consumer workers started')

    try:
        await asyncio.gather(outbox_worker.run(), webhook_worker.run())
    except asyncio.CancelledError:
        logger.info('Payments consumer workers cancelled')
    finally:
        await broker.stop()
        await dispose_engine()


if __name__ == '__main__':
    asyncio.run(main())
