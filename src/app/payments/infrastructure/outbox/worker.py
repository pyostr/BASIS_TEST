"""Воркер публикации транзакционного outbox.

Опрашивает таблицу outbox и публикует ожидающие сообщения в RabbitMQ
с семантикой at-least-once. Захват и фиксация результата выполняются в
коротких транзакциях, а сама публикация — вне транзакции: неудавшиеся
сообщения получают next_retry_at (экспоненциальный backoff) и после
исчерпания OUTBOX_MAX_ATTEMPTS переводятся в статус dead.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.app.payments.domain.repositories.outbox import OutboxMessage
from src.app.payments.infrastructure.uow import SqlAlchemyPaymentsUnitOfWork
from src.config.settings import Settings
from src.runtime.observability.metrics import metrics

logger = logging.getLogger(__name__)


class OutboxWorker:
    """Опрашивает outbox_messages и публикует их в RabbitMQ (at-least-once)."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        broker: RabbitBroker,
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._broker = broker
        self._settings = settings
        self._uow_factory = lambda: SqlAlchemyPaymentsUnitOfWork(sessionmaker)

    async def run(self) -> None:
        """Цикл опроса: публикует пакет, затем спит OUTBOX_POLL_INTERVAL.

        Исключения внутри пакета перехватываются и логируются, чтобы цикл
        переживал кратковременные сбои брокера/БД; отмена распространяется для остановки.
        """
        while True:
            metrics.worker_cycles_total.labels(worker='outbox').inc()
            try:
                await self._publish_batch()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('Outbox worker batch failed')
            await asyncio.sleep(self._settings.OUTBOX_POLL_INTERVAL)

    async def _publish_batch(self) -> None:
        now = datetime.now(UTC)

        # Шаг 1: захват — короткая транзакция, без сетевых вызовов.
        async with self._uow_factory() as uow:
            messages = await uow.outbox_repository.claim_batch(
                self._settings.OUTBOX_BATCH_SIZE, now
            )
        if not messages:
            return

        exchange = RabbitExchange(
            name=self._settings.RABBITMQ_EXCHANGE,
            type=ExchangeType(self._settings.RABBITMQ_EXCHANGE_TYPE),
            durable=True,
        )

        # Шаг 2: публикация
        published: list[UUID] = []
        failed: list[OutboxMessage] = []
        for message in messages:
            try:
                await asyncio.wait_for(
                    self._broker.publish(
                        message=message.payload,
                        exchange=exchange,
                        routing_key=self._settings.RABBITMQ_ROUTING_KEY,
                        correlation_id=message.correlation_id,
                        message_id=str(message.id),
                        headers={'request_id': message.correlation_id or ''},
                    ),
                    timeout=self._settings.RABBITMQ_PUBLISH_TIMEOUT,
                )
            except Exception as exc:
                logger.warning(
                    'Failed to publish outbox message %s (attempts=%d): %s',
                    message.id,
                    message.attempts + 1,
                    exc,
                )
                metrics.outbox_messages_total.labels(status='failed').inc()
                failed.append(message)
            else:
                logger.debug('Published outbox message %s', message.id)
                metrics.outbox_messages_total.labels(status='published').inc()
                published.append(message.id)

        if not published and not failed:
            return

        # Шаг 3: фиксация результатов — короткая транзакция
        async with self._uow_factory() as uow:
            for message_id in published:
                await uow.outbox_repository.mark_processed(message_id)
            for message in failed:
                next_attempts = message.attempts + 1
                await uow.outbox_repository.mark_publish_failure(
                    message.id,
                    max_attempts=self._settings.OUTBOX_MAX_ATTEMPTS,
                    next_retry_at=self._next_retry_at(next_attempts, now),
                )
                if next_attempts >= self._settings.OUTBOX_MAX_ATTEMPTS:
                    metrics.outbox_messages_total.labels(status='dead').inc()
            await uow.commit()

    def _next_retry_at(self, attempts: int, now: datetime) -> datetime | None:
        """Возвращает время следующего захвата или None для статуса dead."""
        if attempts >= self._settings.OUTBOX_MAX_ATTEMPTS:
            return None
        delay = min(
            self._settings.OUTBOX_RETRY_BASE_DELAY * (2 ** (attempts - 1)),
            self._settings.OUTBOX_RETRY_MAX_DELAY,
        )
        return now + timedelta(seconds=delay)


__all__ = ['OutboxWorker']
