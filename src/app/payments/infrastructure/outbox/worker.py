"""Воркер публикации транзакционного outbox.

Опрашивает таблицу outbox и публикует ожидающие сообщения в RabbitMQ
с семантикой at-least-once. Захват использует lease (status=processing,
claimed_at/claimed_by): конкурентные воркеры не обрабатывают одно сообщение
одновременно, а после OUTBOX_CLAIM_TIMEOUT просроченные захваты снимаются
(исчерпавшие лимит попыток — сразу в dead). Публикация выполняется вне
транзакций с ограниченной конкурентностью (OUTBOX_PUBLISH_CONCURRENCY);
неудавшиеся сообщения получают next_retry_at (экспоненциальный backoff с
jitter) и после исчерпания OUTBOX_MAX_ATTEMPTS переводятся в статус dead.
Терминальные строки периодически вычищаются (OUTBOX_RETENTION_SECONDS).
"""

import asyncio
import logging
import random
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

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
        self._worker_id = uuid4()
        self._uow_factory = lambda: SqlAlchemyPaymentsUnitOfWork(sessionmaker)
        self._cycles = 0

    async def run(self) -> None:
        """Цикл опроса: публикует пакет, периодически чистит старые строки и спит.

        Исключения внутри пакета перехватываются и логируются, чтобы цикл
        переживал кратковременные сбои брокера/БД; отмена распространяется для
        остановки.
        """
        while True:
            metrics.worker_cycles_total.labels(worker='outbox').inc()
            try:
                await self._publish_batch()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('Outbox worker batch failed')

            self._cycles += 1
            if self._cycles % self._settings.OUTBOX_PURGE_INTERVAL == 0:
                try:
                    await self._purge_processed()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception('Outbox purge failed')

            await asyncio.sleep(self._settings.OUTBOX_POLL_INTERVAL)

    async def _publish_batch(self) -> None:
        now = datetime.now(UTC)

        # Шаг 1: снять просроченные lease и атомарно захватить пакет
        # (короткая транзакция, без сетевых вызовов).
        async with self._uow_factory() as uow:
            (
                released_dead,
                released_pending,
            ) = await uow.outbox_repository.release_expired_claims(
                now,
                self._settings.OUTBOX_CLAIM_TIMEOUT,
                self._settings.OUTBOX_MAX_ATTEMPTS,
            )
            if released_dead:
                metrics.outbox_claims_released_total.labels(dest='dead').inc(
                    released_dead
                )
            if released_pending:
                metrics.outbox_claims_released_total.labels(dest='pending').inc(
                    released_pending
                )
            messages = await uow.outbox_repository.claim_batch(
                self._settings.OUTBOX_BATCH_SIZE,
                now,
                self._worker_id,
                self._settings.OUTBOX_MAX_ATTEMPTS,
            )
            await uow.commit()
        if not messages:
            return

        if messages:
            oldest = min(m.created_at for m in messages)
            metrics.outbox_lag_seconds.set((now - oldest).total_seconds())

        exchange = RabbitExchange(
            name=self._settings.RABBITMQ_EXCHANGE,
            type=ExchangeType(self._settings.RABBITMQ_EXCHANGE_TYPE),
            durable=True,
        )

        # Шаг 2: публикация — вне транзакции, чтобы не держать блокировки БД,
        # с ограниченной конкурентностью внутри батча.
        semaphore = asyncio.Semaphore(self._settings.OUTBOX_PUBLISH_CONCURRENCY)

        async def _publish(message: OutboxMessage) -> OutboxMessage | None:
            async with semaphore:
                return await self._publish_one(message, exchange)

        results = await asyncio.gather(*(_publish(m) for m in messages))
        failed = [m for m in results if m is not None]
        failed_ids = {m.id for m in failed}
        published = [m.id for m in messages if m.id not in failed_ids]

        if not published and not failed:
            return

        # Шаг 3: фиксация результатов публикации — короткая транзакция.
        async with self._uow_factory() as uow:
            for message_id in published:
                await uow.outbox_repository.mark_processed(message_id, self._worker_id)
            for message in failed:
                next_retry_at = self._next_retry_at(message.attempts, now)
                await uow.outbox_repository.mark_publish_failure(
                    message.id,
                    worker_id=self._worker_id,
                    max_attempts=self._settings.OUTBOX_MAX_ATTEMPTS,
                    next_retry_at=next_retry_at,
                )
                if next_retry_at is None:
                    metrics.outbox_messages_total.labels(status='dead').inc()
            await uow.commit()

    async def _publish_one(
        self, message: OutboxMessage, exchange: RabbitExchange
    ) -> OutboxMessage | None:
        """Публикует одно сообщение и возвращает его при неудаче (иначе None)."""
        start = time.perf_counter()
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
                message.attempts,
                exc,
            )
            metrics.outbox_messages_total.labels(status='failed').inc()
            return message
        else:
            logger.debug('Published outbox message %s', message.id)
            metrics.outbox_messages_total.labels(status='published').inc()
            return None
        finally:
            metrics.outbox_publish_duration_seconds.observe(time.perf_counter() - start)

    def _next_retry_at(self, attempts: int, now: datetime) -> datetime | None:
        """Возвращает время следующего захвата или None для статуса dead.

        ``attempts`` уже увеличен ``claim_batch``: первая неудача даёт базовую
        задержку, далее экспоненциальный рост. При ``attempts >= max_attempts``
        возвращает None — сообщение сразу переходит в ``dead``.
        """
        if attempts >= self._settings.OUTBOX_MAX_ATTEMPTS:
            return None
        delay = min(
            self._settings.OUTBOX_RETRY_BASE_DELAY * (2 ** (attempts - 1)),
            self._settings.OUTBOX_RETRY_MAX_DELAY,
        )
        jitter = self._settings.OUTBOX_RETRY_JITTER
        if jitter:
            delay *= random.uniform(1.0, 1.0 + jitter)
        return now + timedelta(seconds=delay)

    async def _purge_processed(self) -> None:
        """Retention: удаляет терминальные строки старше OUTBOX_RETENTION_SECONDS."""
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=self._settings.OUTBOX_RETENTION_SECONDS)
        async with self._uow_factory() as uow:
            await uow.outbox_repository.reap_exhausted(
                self._settings.OUTBOX_MAX_ATTEMPTS
            )
            await uow.outbox_repository.purge_processed(cutoff)
            await uow.commit()


__all__ = ['OutboxWorker']
