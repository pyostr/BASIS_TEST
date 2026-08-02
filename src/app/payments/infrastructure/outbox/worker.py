"""Воркер публикации транзакционного outbox.

Опрашивает таблицу outbox и публикует ожидающие сообщения в RabbitMQ
с семантикой at-least-once (ошибки пакета логируются и повторяются при следующем опросе).
"""

import asyncio
import logging

from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
        exchange = RabbitExchange(
            name=self._settings.RABBITMQ_EXCHANGE,
            type=ExchangeType(self._settings.RABBITMQ_EXCHANGE_TYPE),
            durable=True,
        )

        async with self._uow_factory() as uow:
            messages = await uow.outbox_repository.claim_batch(
                self._settings.OUTBOX_BATCH_SIZE
            )
            if not messages:
                return

            for message in messages:
                # Сообщения, публикация которых не удалась, сохраняют processed_at = NULL
                # (увеличивается только attempts), чтобы следующий опрос снова их захватил.
                try:
                    await self._broker.publish(
                        message=message.payload,
                        exchange=exchange,
                        routing_key=self._settings.RABBITMQ_ROUTING_KEY,
                        correlation_id=message.correlation_id,
                        message_id=str(message.id),
                        headers={'request_id': message.correlation_id or ''},
                    )
                except Exception as exc:
                    logger.warning(
                        'Failed to publish outbox message %s (attempts=%d): %s',
                        message.id,
                        message.attempts + 1,
                        exc,
                    )
                    metrics.outbox_messages_total.labels(status='failed').inc()
                    await uow.outbox_repository.mark_publish_failure(message.id)
                else:
                    logger.debug('Published outbox message %s', message.id)
                    metrics.outbox_messages_total.labels(status='published').inc()
                    await uow.outbox_repository.mark_processed(message.id)

            await uow.commit()


__all__ = ['OutboxWorker']
