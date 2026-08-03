"""Тесты outbox-воркера, который публикует outbox-сообщения в брокер
и помечает их обработанными."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from tests.payments.fakes import FakeBroker
from tests.payments.helpers import NOW

from src.app.payments.infrastructure.models.outbox_message import OutboxMessageModel
from src.app.payments.infrastructure.outbox.worker import OutboxWorker
from src.app.payments.infrastructure.repositories.outbox import (
    SqlAlchemyOutboxRepository,
)
from src.app.payments.infrastructure.uow import SqlAlchemyPaymentsUnitOfWork
from src.config.settings import Settings
from src.shared.utils.uuid import uuid7


async def _seed_outbox(
    sessionmaker, count: int = 1, payload: dict | None = None, **overrides
):
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
                    **{'attempts': 0, 'processed_at': None, **overrides},
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


class _ConcurrentBroker:
    """Брокер, фиксирующий максимальное число одновременных публикаций."""

    def __init__(self) -> None:
        self._active = 0
        self.max_active = 0
        self.published = []
        self._release = asyncio.Event()

    async def publish(self, message, **kwargs) -> None:
        self._active += 1
        self.max_active = max(self.max_active, self._active)
        self.published.append(message)
        try:
            await asyncio.wait_for(self._release.wait(), timeout=2.0)
        finally:
            self._active -= 1

    def release_all(self) -> None:
        self._release.set()


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
        """Неудачная публикация увеличивает счётчик попыток и снимает lease."""
        [msg_id] = await _seed_outbox(sessionmaker)
        worker = OutboxWorker(sessionmaker, FakeBroker(fail=True), Settings())

        await worker._publish_batch()

        async with sessionmaker() as session:
            row = await session.get(OutboxMessageModel, msg_id)
            assert row is not None
            assert row.attempts == 1
            assert row.status == 'pending'
            assert row.next_retry_at is not None
            assert row.claimed_at is None
            assert row.claimed_by is None
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
            assert (
                await repo.claim_batch(
                    10, datetime.now(UTC), uuid7(), Settings().OUTBOX_MAX_ATTEMPTS
                )
                == []
            )

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
            assert row.claimed_at is None
            assert row.claimed_by is None
            assert row.processed_at is None

            repo = SqlAlchemyOutboxRepository(lambda: session)
            assert (
                await repo.claim_batch(
                    10, datetime.now(UTC), uuid7(), Settings().OUTBOX_MAX_ATTEMPTS
                )
                == []
            )

    async def test_max_attempts_boundary_three_failures(self, sessionmaker):
        """OUTBOX_MAX_ATTEMPTS — число реальных попыток: dead наступает только после последней."""
        settings = Settings(OUTBOX_MAX_ATTEMPTS=3, OUTBOX_RETRY_BASE_DELAY=0.0)
        [msg_id] = await _seed_outbox(sessionmaker)
        worker = OutboxWorker(sessionmaker, FakeBroker(fail=True), settings)

        await worker._publish_batch()
        async with sessionmaker() as session:
            row = await session.get(OutboxMessageModel, msg_id)
            assert row.attempts == 1
            assert row.status == 'pending'

        await worker._publish_batch()
        async with sessionmaker() as session:
            row = await session.get(OutboxMessageModel, msg_id)
            assert row.attempts == 2
            assert row.status == 'pending'

        await worker._publish_batch()
        async with sessionmaker() as session:
            row = await session.get(OutboxMessageModel, msg_id)
            assert row.attempts == 3
            assert row.status == 'dead'
            assert row.next_retry_at is None
            assert row.claimed_at is None
            assert row.claimed_by is None

            repo = SqlAlchemyOutboxRepository(lambda: session)
            assert (
                await repo.claim_batch(
                    10, datetime.now(UTC), uuid7(), Settings().OUTBOX_MAX_ATTEMPTS
                )
                == []
            )

    def test_next_retry_at_exponential_backoff(self):
        """Backoff использует уже увеличенный attempts: base, base*2, base*4."""
        settings = Settings(OUTBOX_MAX_ATTEMPTS=5)
        worker = OutboxWorker(None, None, settings)
        now = datetime.now(UTC)
        base = settings.OUTBOX_RETRY_BASE_DELAY

        assert worker._next_retry_at(1, now) == now + timedelta(seconds=base)
        assert worker._next_retry_at(2, now) == now + timedelta(seconds=base * 2)
        assert worker._next_retry_at(3, now) == now + timedelta(seconds=base * 4)
        assert worker._next_retry_at(settings.OUTBOX_MAX_ATTEMPTS, now) is None

    def test_next_retry_at_jitter(self):
        """Jitter сдвигает задержку в диапазон [base, base * (1 + jitter)]."""
        settings = Settings(OUTBOX_MAX_ATTEMPTS=5, OUTBOX_RETRY_JITTER=1.0)
        worker = OutboxWorker(None, None, settings)
        now = datetime.now(UTC)
        base = settings.OUTBOX_RETRY_BASE_DELAY

        for _ in range(50):
            retry = worker._next_retry_at(1, now)
            assert retry is not None
            delay = (retry - now).total_seconds()
            assert base <= delay <= base * 2

    async def test_batch_publishes_concurrently(self, sessionmaker):
        """Публикация внутри батча идёт с ограниченной конкурентностью, а не последовательно."""
        await _seed_outbox(sessionmaker, count=3)
        broker = _ConcurrentBroker()
        worker = OutboxWorker(
            sessionmaker, broker, Settings(OUTBOX_PUBLISH_CONCURRENCY=3)
        )

        task = asyncio.create_task(worker._publish_batch())
        for _ in range(100):
            if broker.max_active >= 3:
                break
            await asyncio.sleep(0.01)
        assert broker.max_active >= 2

        broker.release_all()
        await asyncio.wait_for(task, timeout=5.0)
        assert len(broker.published) == 3

    async def test_purge_removes_terminal_rows(self, sessionmaker):
        """Retention-чистка удаляет старые терминальные строки, не трогая pending."""
        settings = Settings(OUTBOX_RETENTION_SECONDS=60)
        [old_id] = await _seed_outbox(
            sessionmaker,
            status='processed',
            processed_at=NOW - timedelta(hours=1),
            finished_at=NOW - timedelta(hours=1),
        )
        [fresh_id] = await _seed_outbox(sessionmaker)

        worker = OutboxWorker(sessionmaker, FakeBroker(), settings)
        await worker._purge_processed()

        async with sessionmaker() as session:
            assert await session.get(OutboxMessageModel, old_id) is None
            assert await session.get(OutboxMessageModel, fresh_id) is not None

    async def test_concurrent_claim_only_one_worker(self, sessionmaker):
        """Одно сообщение захватывается только одним воркером."""
        [msg_id] = await _seed_outbox(sessionmaker)
        worker_a = OutboxWorker(sessionmaker, FakeBroker(), Settings())
        worker_b = OutboxWorker(sessionmaker, FakeBroker(), Settings())

        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            claimed_a = await uow.outbox_repository.claim_batch(
                10,
                datetime.now(UTC),
                worker_a._worker_id,
                Settings().OUTBOX_MAX_ATTEMPTS,
            )
            await uow.commit()
        assert [m.id for m in claimed_a] == [msg_id]

        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            claimed_b = await uow.outbox_repository.claim_batch(
                10,
                datetime.now(UTC),
                worker_b._worker_id,
                Settings().OUTBOX_MAX_ATTEMPTS,
            )
            await uow.commit()
        assert claimed_b == []

    async def test_worker_reclaims_after_crash(self, sessionmaker):
        """Упавший воркер не блокирует сообщение: после истечения lease его забирает другой."""
        [msg_id] = await _seed_outbox(sessionmaker)
        worker_a = OutboxWorker(sessionmaker, FakeBroker(), Settings())
        worker_b = OutboxWorker(sessionmaker, FakeBroker(), Settings())

        # worker A захватывает сообщение и «падает», не пометив результат.
        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            claimed = await uow.outbox_repository.claim_batch(
                10,
                datetime.now(UTC),
                worker_a._worker_id,
                Settings().OUTBOX_MAX_ATTEMPTS,
            )
            await uow.commit()
        assert len(claimed) == 1

        # Свежий lease: worker B сообщение не видит.
        await worker_b._publish_batch()
        assert worker_b._broker.published == []

        # «Проходит» время: lease истекает.
        async with sessionmaker() as session:
            await session.execute(
                update(OutboxMessageModel)
                .where(OutboxMessageModel.id == msg_id)
                .values(claimed_at=datetime.now(UTC) - timedelta(seconds=301))
            )
            await session.commit()

        # Worker B снимает просроченный lease и публикует сообщение.
        await worker_b._publish_batch()
        assert len(worker_b._broker.published) == 1

    async def test_worker_crash_at_max_expires_to_dead(self, sessionmaker):
        """Crash на последней попытке: после истечения lease воркер переводит сообщение в dead, а не в pending."""
        settings = Settings(OUTBOX_MAX_ATTEMPTS=3, OUTBOX_RETRY_BASE_DELAY=0.0)
        [msg_id] = await _seed_outbox(sessionmaker, attempts=2)
        worker_a = OutboxWorker(sessionmaker, FakeBroker(), settings)
        worker_b = OutboxWorker(sessionmaker, FakeBroker(), settings)

        # Worker A захватывает сообщение на последней попытке и «падает».
        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            claimed = await uow.outbox_repository.claim_batch(
                10, datetime.now(UTC), worker_a._worker_id, settings.OUTBOX_MAX_ATTEMPTS
            )
            await uow.commit()
        assert [m.id for m in claimed] == [msg_id]

        # Lease истекает, worker B запускает цикл: release -> dead (попытки исчерпаны).
        async with sessionmaker() as session:
            await session.execute(
                update(OutboxMessageModel)
                .where(OutboxMessageModel.id == msg_id)
                .values(claimed_at=datetime.now(UTC) - timedelta(seconds=301))
            )
            await session.commit()

        await worker_b._publish_batch()
        assert worker_b._broker.published == []

        async with sessionmaker() as session:
            row = await session.get(OutboxMessageModel, msg_id)
            assert row.status == 'dead'
            assert row.attempts == settings.OUTBOX_MAX_ATTEMPTS
            assert row.next_retry_at is None
            assert row.finished_at is not None

            repo = SqlAlchemyOutboxRepository(lambda: session)
            assert (
                await repo.claim_batch(
                    10, datetime.now(UTC), uuid7(), settings.OUTBOX_MAX_ATTEMPTS
                )
                == []
            )

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
