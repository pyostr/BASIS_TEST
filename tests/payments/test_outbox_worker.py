"""Тесты outbox-воркера, который публикует outbox-сообщения в брокер
и помечает их обработанными."""

import asyncio
from datetime import UTC, datetime

from tests.payments.fakes import FakeBroker
from tests.payments.helpers import NOW

from src.app.payments.infrastructure.models.outbox_message import OutboxMessageModel
from src.app.payments.infrastructure.outbox.worker import OutboxWorker
from src.app.payments.infrastructure.repositories.outbox import (
    SqlAlchemyOutboxRepository,
)
from src.config.settings import Settings
from src.shared.utils.uuid import uuid7


async def _seed_outbox(sessionmaker, count: int = 1, payload: dict | None = None, **overrides):
    """Вставляет count необработанных outbox-строк и возвращает их id."""
    ids = []
    async with sessionmaker() as session:
        for _ in range(count):
            msg_id = uuid7()
            ids.append(msg_id)
            session.add(
                OutboxMessageModel(
                    id=msg_id,
                    event_type='PaymentCreated',
                    aggregate_id=uuid7(),
                    payload=payload or {'event_type': 'PaymentCreated'},
                    correlation_id='corr-1',
                    created_at=NOW,
                    processed_at=None,
                    **{'attempts': 0, **overrides},
                )
            )
        await session.commit()
    return ids


async def _count(sessionmaker, table: str) -> int:
    """Возвращает количество строк в указанной таблице."""
    async with sessionmaker() as session:
        from sqlalchemy import text

        result = await session.execute(text(f'SELECT count(*) FROM {table}'))
        return result.scalar_one()


class _HangingBroker:
    """Брокер, у которого publish никогда не завершается сам по себе."""

    async def publish(self, message, **kwargs) -> None:
        await asyncio.sleep(60)


class TestOutboxWorker:
    """Сценарии outbox-воркера: публикация, пакетная обработка, обработка сбоев и пустые пакеты."""

    async def test_publishes_and_marks_processed(self, sessionmaker):
        """Ожидающее outbox-сообщение публикуется с корректными метаданными и помечается обработанным."""
        [msg_id] = await _seed_outbox(sessionmaker)
        broker = FakeBroker()
        worker = OutboxWorker(sessionmaker, broker, Settings())

        await worker._publish_batch()

        assert len(broker.published) == 1
        published, kwargs = broker.published[0]
        assert published == {'event_type': 'PaymentCreated'}
        assert kwargs['message_id'] == str(msg_id)
        assert kwargs['correlation_id'] == 'corr-1'
        assert kwargs['headers'] == {'request_id': 'corr-1'}
        assert kwargs['routing_key'] == Settings().RABBITMQ_ROUTING_KEY

        async with sessionmaker() as session:
            from sqlalchemy import text

            result = await session.execute(
                text('SELECT processed_at FROM outbox_messages WHERE id = :id'),
                {'id': msg_id},
            )
            assert result.scalar_one() is not None

    async def test_batch_publishes_all(self, sessionmaker):
        """Пакет сообщений публикуется полностью."""
        await _seed_outbox(sessionmaker, count=3)
        broker = FakeBroker()
        worker = OutboxWorker(sessionmaker, broker, Settings())

        await worker._publish_batch()

        assert len(broker.published) == 3

    async def test_publish_failure_increments_attempts(self, sessionmaker):
        """Неудачная публикация увеличивает счётчик попыток и откладывает повторный захват."""
        [msg_id] = await _seed_outbox(sessionmaker)
        worker = OutboxWorker(sessionmaker, FakeBroker(fail=True), Settings())

        await worker._publish_batch()

        async with sessionmaker() as session:
            row = await session.get(OutboxMessageModel, msg_id)
            assert row is not None
            assert row.attempts == 1
            assert row.status == 'pending'
            assert row.next_retry_at is not None
            assert row.processed_at is None

    async def test_failed_message_not_reclaimed_until_backoff(self, sessionmaker):
        """Сообщение с future next_retry_at не захватывается следующим опросом."""
        [msg_id] = await _seed_outbox(sessionmaker)
        worker = OutboxWorker(sessionmaker, FakeBroker(fail=True), Settings())

        await worker._publish_batch()

        async with sessionmaker() as session:
            row = await session.get(OutboxMessageModel, msg_id)
            assert row.next_retry_at > datetime.now(UTC)

            repo = SqlAlchemyOutboxRepository(lambda: session)
            assert await repo.claim_batch(10, datetime.now(UTC)) == []

    async def test_dead_after_max_attempts(self, sessionmaker):
        """Исчерпание попыток переводит сообщение в статус dead и исключает из захвата."""
        [msg_id] = await _seed_outbox(
            sessionmaker,
            attempts=Settings().OUTBOX_MAX_ATTEMPTS - 1,
        )
        worker = OutboxWorker(sessionmaker, FakeBroker(fail=True), Settings())

        await worker._publish_batch()

        async with sessionmaker() as session:
            row = await session.get(OutboxMessageModel, msg_id)
            assert row is not None
            assert row.attempts == Settings().OUTBOX_MAX_ATTEMPTS
            assert row.status == 'dead'
            assert row.next_retry_at is None
            assert row.processed_at is None

            repo = SqlAlchemyOutboxRepository(lambda: session)
            assert await repo.claim_batch(10, datetime.now(UTC)) == []

    async def test_no_messages_no_publish(self, sessionmaker):
        """При отсутствии ожидающих сообщений воркер ничего не публикует."""
        broker = FakeBroker()
        worker = OutboxWorker(sessionmaker, broker, Settings())

        await worker._publish_batch()

        assert broker.published == []

    async def test_hanging_publish_hits_timeout(self, sessionmaker):
        """Зависшая публикация прерывается по таймауту и сообщение остаётся необработанным."""
        [msg_id] = await _seed_outbox(sessionmaker)
        worker = OutboxWorker(
            sessionmaker,
            _HangingBroker(),
            Settings(RABBITMQ_PUBLISH_TIMEOUT=0.01),
        )

        await worker._publish_batch()

        async with sessionmaker() as session:
            row = await session.get(OutboxMessageModel, msg_id)
            assert row is not None
            assert row.attempts == 1
            assert row.processed_at is None
