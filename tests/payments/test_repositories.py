"""Интеграционные тесты SQLAlchemy-репозиториев: захват (claim) жизненного цикла
платежей, захват outbox и сохранение попыток/доставок вебхуков."""

from datetime import datetime, timedelta

from sqlalchemy import text
from tests.payments.helpers import NOW, build_payment, insert_payment

from src.app.payments.domain.aggregates.payment import PaymentStatus
from src.app.payments.domain.entities.attempt import PaymentAttempt
from src.app.payments.domain.entities.webhook_delivery import WebhookDelivery
from src.app.payments.domain.value_objects.money import Currency, Money
from src.app.payments.infrastructure.models.outbox_message import OutboxMessageModel
from src.app.payments.infrastructure.repositories.attempt import (
    SqlAlchemyAttemptRepository,
)
from src.app.payments.infrastructure.repositories.outbox import (
    SqlAlchemyOutboxRepository,
)
from src.app.payments.infrastructure.repositories.payment import (
    SqlAlchemyPaymentRepository,
)
from src.app.payments.infrastructure.repositories.webhook_delivery import (
    SqlAlchemyWebhookDeliveryRepository,
)
from src.app.payments.infrastructure.uow import SqlAlchemyPaymentsUnitOfWork
from src.shared.utils.uuid import uuid7


async def _count(sessionmaker, table: str) -> int:
    """Возвращает количество строк в указанной таблице."""
    async with sessionmaker() as session:
        result = await session.execute(text(f'SELECT count(*) FROM {table}'))
        return result.scalar_one()


class TestPaymentRepository:
    """Сценарии репозитория платежей: вставка/получение по кругу, конфликты идемпотентности и переходы с оптимистичной блокировкой."""

    async def test_try_insert_and_get(self, sessionmaker):
        """Сохранённый платёж проходит через репозиторий по кругу со всеми полями без изменений."""
        payment = build_payment()
        await insert_payment(sessionmaker, payment)

        async with sessionmaker() as session:
            repo = SqlAlchemyPaymentRepository(lambda: session)
            loaded = await repo.get(payment.id)

        assert loaded is not None
        assert loaded.status is PaymentStatus.PENDING
        assert loaded.money.amount == Money('100.00', Currency.RUB).amount
        assert str(loaded.idempotency_key) == 'key-1'
        assert loaded.webhook_url == 'https://example.com/hook'

    async def test_try_insert_unique_key_conflict(self, sessionmaker):
        """Вставка дублирующего idempotency-ключа возвращает None, а исходная строка сохраняется."""
        payment = build_payment(idempotency_key='same-key')
        await insert_payment(sessionmaker, payment)

        duplicate = build_payment(idempotency_key='same-key')
        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            inserted = await uow.payment_repository.try_insert(duplicate)
            existing = await uow.payment_repository.get_by_idempotency_key('same-key')
            await uow.commit()

        assert inserted is None
        assert existing is not None
        assert existing.id == payment.id
        assert await _count(sessionmaker, 'payments') == 1

    async def test_begin_processing_atomic(self, sessionmaker):
        """Захват платежа для обработки переводит его в PROCESSING и увеличивает версию."""
        payment = build_payment()
        await insert_payment(sessionmaker, payment)

        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            claimed = await uow.payment_repository.begin_processing(
                payment.id, expected_version=0, expected_status=PaymentStatus.PENDING
            )
            await uow.commit()

        assert claimed is True

        async with sessionmaker() as session:
            repo = SqlAlchemyPaymentRepository(lambda: session)
            loaded = await repo.get(payment.id)

        assert loaded is not None
        assert loaded.status is PaymentStatus.PROCESSING
        assert loaded.version == 1

    async def test_begin_processing_version_conflict(self, sessionmaker):
        """Захват с устаревшей версией отклоняется, и платёж остаётся в PENDING."""
        payment = build_payment()
        await insert_payment(sessionmaker, payment)

        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            claimed = await uow.payment_repository.begin_processing(
                payment.id, expected_version=5, expected_status=PaymentStatus.PENDING
            )
            await uow.commit()

        assert claimed is False

        async with sessionmaker() as session:
            repo = SqlAlchemyPaymentRepository(lambda: session)
            loaded = await repo.get(payment.id)

        assert loaded is not None
        assert loaded.status is PaymentStatus.PENDING

    async def test_begin_processing_on_processing_conflict(self, sessionmaker):
        """Платёж, уже захваченный для обработки, не может быть захвачен повторно."""
        payment = build_payment()
        await insert_payment(sessionmaker, payment)

        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            await uow.payment_repository.begin_processing(
                payment.id, 0, PaymentStatus.PENDING
            )
            second = await uow.payment_repository.begin_processing(
                payment.id, 1, PaymentStatus.PENDING
            )
            await uow.commit()

        assert second is False

    async def test_mark_succeeded(self, sessionmaker):
        """Пометка захваченного платежа как успешного сохраняет время обработки и увеличивает версию."""
        payment = build_payment()
        await insert_payment(sessionmaker, payment)

        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            await uow.payment_repository.begin_processing(
                payment.id, 0, PaymentStatus.PENDING
            )
            ok = await uow.payment_repository.mark_succeeded(
                payment.id,
                expected_version=1,
                expected_status=PaymentStatus.PROCESSING,
                processed_at=NOW,
            )
            await uow.commit()

        assert ok is True

        async with sessionmaker() as session:
            repo = SqlAlchemyPaymentRepository(lambda: session)
            loaded = await repo.get(payment.id)

        assert loaded is not None
        assert loaded.status is PaymentStatus.SUCCEEDED
        assert loaded.processed_at == NOW
        assert loaded.version == 2

    async def test_mark_succeeded_version_conflict(self, sessionmaker):
        """Пометка успешным с устаревшей ожидаемой версией отклоняется."""
        payment = build_payment()
        await insert_payment(sessionmaker, payment)

        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            await uow.payment_repository.begin_processing(
                payment.id, 0, PaymentStatus.PENDING
            )
            ok = await uow.payment_repository.mark_succeeded(
                payment.id,
                expected_version=99,
                expected_status=PaymentStatus.PROCESSING,
                processed_at=NOW,
            )
            await uow.commit()

        assert ok is False

    async def test_mark_failed(self, sessionmaker):
        """Пометка захваченного платежа неудачным переводит его в FAILED."""
        payment = build_payment()
        await insert_payment(sessionmaker, payment)

        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            await uow.payment_repository.begin_processing(
                payment.id, 0, PaymentStatus.PENDING
            )
            ok = await uow.payment_repository.mark_failed(
                payment.id,
                expected_version=1,
                expected_status=PaymentStatus.PROCESSING,
                processed_at=NOW,
            )
            await uow.commit()

        assert ok is True

        async with sessionmaker() as session:
            repo = SqlAlchemyPaymentRepository(lambda: session)
            loaded = await repo.get(payment.id)

        assert loaded is not None
        assert loaded.status is PaymentStatus.FAILED


class TestOutboxRepository:
    """Сценарии outbox-репозитория: lease-захват, восстановление и фиксация результатов."""

    WORKER_A = uuid7()
    WORKER_B = uuid7()
    MAX_ATTEMPTS = 5

    async def _add_messages(self, sessionmaker, count: int = 1, **overrides) -> list:
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
                        payload={'event_type': 'PaymentCreated'},
                        correlation_id='corr',
                        created_at=NOW,
                        processed_at=None,
                        **{'attempts': 0, **overrides},
                    )
                )
            await session.commit()
        return ids

    async def _claim(
        self,
        sessionmaker,
        worker_id,
        now: datetime = NOW,
        limit: int = 10,
        max_attempts: int = MAX_ATTEMPTS,
    ):
        """Захватывает пакет сообщений от имени воркера и коммитит результат."""
        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            claimed = await uow.outbox_repository.claim_batch(
                limit, now, worker_id, max_attempts
            )
            await uow.commit()
            return claimed

    async def test_claim_batch_claims_pending(self, sessionmaker):
        """Захват переводит ожидающие сообщения в processing с владельцем и инкрементом attempts."""
        ids = await self._add_messages(sessionmaker, 2)

        claimed = await self._claim(sessionmaker, self.WORKER_A)

        assert {m.id for m in claimed} == set(ids)
        assert all(m.status == 'processing' for m in claimed)
        assert all(m.claimed_by == self.WORKER_A for m in claimed)
        assert all(m.attempts == 1 for m in claimed)
        assert all(m.claimed_at == NOW for m in claimed)

    async def test_claim_does_not_reclaim_processing(self, sessionmaker):
        """Захваченное (processing) сообщение недоступно другому воркеру."""
        await self._add_messages(sessionmaker, 1)

        claimed_a = await self._claim(sessionmaker, self.WORKER_A)
        assert len(claimed_a) == 1

        claimed_b = await self._claim(sessionmaker, self.WORKER_B)
        assert claimed_b == []

    async def test_claim_marks_processed(self, sessionmaker):
        """Пометка обработанным исключает сообщение из следующего захвата."""
        [msg_id] = await self._add_messages(sessionmaker, 1)
        await self._claim(sessionmaker, self.WORKER_A)

        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            await uow.outbox_repository.mark_processed(msg_id, self.WORKER_A)
            await uow.commit()

        async with sessionmaker() as session:
            row = await session.get(OutboxMessageModel, msg_id)
            assert row.processed_at is not None
            assert row.status == 'processed'
            assert row.finished_at is not None
            assert row.claimed_at is None
            assert row.claimed_by is None

            repo = SqlAlchemyOutboxRepository(lambda: session)
            assert (
                await repo.claim_batch(10, NOW, self.WORKER_B, self.MAX_ATTEMPTS) == []
            )

    async def test_mark_processed_requires_owner(self, sessionmaker):
        """Воркер не может пометить обработанным чужое захваченное сообщение."""
        [msg_id] = await self._add_messages(sessionmaker, 1)
        await self._claim(sessionmaker, self.WORKER_A)

        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            await uow.outbox_repository.mark_processed(msg_id, self.WORKER_B)
            await uow.commit()

        async with sessionmaker() as session:
            row = await session.get(OutboxMessageModel, msg_id)
            assert row.status == 'processing'
            assert row.claimed_by == self.WORKER_A
            assert row.processed_at is None

    async def test_claim_skips_exhausted_attempts(self, sessionmaker):
        """Строка с attempts >= max_attempts не захватывается повторно."""
        [msg_id] = await self._add_messages(sessionmaker, 1, attempts=3)

        async with sessionmaker() as session:
            repo = SqlAlchemyOutboxRepository(lambda: session)
            assert await repo.claim_batch(10, NOW, self.WORKER_A, 3) == []
            row = await session.get(OutboxMessageModel, msg_id)
            assert row.status == 'pending'

    async def test_reap_exhausted_marks_dead(self, sessionmaker):
        """reap переводит зависшие pending-строки с исчерпанными попытками в dead."""
        [msg_id] = await self._add_messages(sessionmaker, 1, attempts=3)

        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            await uow.outbox_repository.reap_exhausted(3)
            await uow.commit()

        async with sessionmaker() as session:
            row = await session.get(OutboxMessageModel, msg_id)
            assert row.status == 'dead'
            assert row.next_retry_at is None
            assert row.finished_at is not None

    async def test_purge_removes_old_terminal_rows(self, sessionmaker):
        """Purge удаляет терминальные строки старше cutoff и не трогает свежие/pending."""
        old_processed = (
            await self._add_messages(
                sessionmaker,
                1,
                status='processed',
                finished_at=NOW - timedelta(days=2),
            )
        )[0]
        old_dead = (
            await self._add_messages(
                sessionmaker, 1, status='dead', finished_at=NOW - timedelta(days=2)
            )
        )[0]
        fresh_processed = (
            await self._add_messages(
                sessionmaker, 1, status='processed', finished_at=NOW
            )
        )[0]
        [pending_id] = await self._add_messages(sessionmaker, 1)

        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            await uow.outbox_repository.purge_processed(NOW - timedelta(days=1))
            await uow.commit()

        async with sessionmaker() as session:
            assert await session.get(OutboxMessageModel, old_processed) is None
            assert await session.get(OutboxMessageModel, old_dead) is None
            assert await session.get(OutboxMessageModel, fresh_processed) is not None
            assert await session.get(OutboxMessageModel, pending_id) is not None

    async def test_mark_publish_failure_returns_to_pending(self, sessionmaker):
        """Сбой публикации снимает lease и откладывает повторный захват."""
        [msg_id] = await self._add_messages(sessionmaker, 1)
        await self._claim(sessionmaker, self.WORKER_A)

        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            await uow.outbox_repository.mark_publish_failure(
                msg_id,
                worker_id=self.WORKER_A,
                max_attempts=5,
                next_retry_at=NOW + timedelta(seconds=2),
            )
            await uow.commit()

        async with sessionmaker() as session:
            row = await session.get(OutboxMessageModel, msg_id)
            assert row is not None
            assert row.attempts == 1
            assert row.status == 'pending'
            assert row.next_retry_at == NOW + timedelta(seconds=2)
            assert row.claimed_at is None
            assert row.claimed_by is None
            assert row.processed_at is None

            repo = SqlAlchemyOutboxRepository(lambda: session)
            assert (
                await repo.claim_batch(10, NOW, self.WORKER_B, self.MAX_ATTEMPTS) == []
            )

    async def test_mark_publish_failure_marks_dead_at_max(self, sessionmaker):
        """Достижение max_attempts переводит сообщение в статус dead и исключает из захвата."""
        [msg_id] = await self._add_messages(sessionmaker, 1, attempts=2)
        await self._claim(sessionmaker, self.WORKER_A)

        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            await uow.outbox_repository.mark_publish_failure(
                msg_id,
                worker_id=self.WORKER_A,
                max_attempts=3,
                next_retry_at=None,
            )
            await uow.commit()

        async with sessionmaker() as session:
            row = await session.get(OutboxMessageModel, msg_id)
            assert row is not None
            assert row.attempts == 3
            assert row.status == 'dead'
            assert row.next_retry_at is None
            assert row.claimed_at is None
            assert row.claimed_by is None
            assert row.processed_at is None

            repo = SqlAlchemyOutboxRepository(lambda: session)
            assert (
                await repo.claim_batch(10, NOW, self.WORKER_B, self.MAX_ATTEMPTS) == []
            )

    async def test_claim_skips_future_retry(self, sessionmaker):
        """Сообщение с next_retry_at в будущем не захватывается, пока время не наступит."""
        await self._add_messages(
            sessionmaker, 1, next_retry_at=NOW + timedelta(seconds=30)
        )

        async with sessionmaker() as session:
            repo = SqlAlchemyOutboxRepository(lambda: session)
            assert (
                await repo.claim_batch(10, NOW, self.WORKER_A, self.MAX_ATTEMPTS) == []
            )
            assert (
                len(
                    await repo.claim_batch(
                        10,
                        NOW + timedelta(seconds=31),
                        self.WORKER_A,
                        self.MAX_ATTEMPTS,
                    )
                )
                == 1
            )

    async def test_release_expired_claims_keeps_fresh(self, sessionmaker):
        """Свежий lease не снимается."""
        [msg_id] = await self._add_messages(sessionmaker, 1)
        await self._claim(sessionmaker, self.WORKER_A)

        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            await uow.outbox_repository.release_expired_claims(
                NOW + timedelta(seconds=10), 300, self.MAX_ATTEMPTS
            )
            await uow.commit()

        async with sessionmaker() as session:
            row = await session.get(OutboxMessageModel, msg_id)
            assert row.status == 'processing'
            assert row.claimed_by == self.WORKER_A

    async def test_release_expired_claims_restores_pending(self, sessionmaker):
        """Просроченный lease возвращает сообщение в pending, и его забирает другой воркер."""
        [msg_id] = await self._add_messages(sessionmaker, 1)
        await self._claim(sessionmaker, self.WORKER_A)

        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            await uow.outbox_repository.release_expired_claims(
                NOW + timedelta(seconds=301), 300, self.MAX_ATTEMPTS
            )
            await uow.commit()

        async with sessionmaker() as session:
            row = await session.get(OutboxMessageModel, msg_id)
            assert row.status == 'pending'
            assert row.claimed_at is None
            assert row.claimed_by is None

        claimed = await self._claim(sessionmaker, self.WORKER_B)
        assert [m.id for m in claimed] == [msg_id]

    async def test_release_expired_claims_marks_dead_at_max(self, sessionmaker):
        """Просроченный lease сообщения с исчерпанными попытками уходит в dead, а не в pending."""
        [msg_id] = await self._add_messages(sessionmaker, 1, attempts=2)
        claimed = await self._claim(sessionmaker, self.WORKER_A, max_attempts=3)
        assert [m.id for m in claimed] == [msg_id]

        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            released = await uow.outbox_repository.release_expired_claims(
                NOW + timedelta(seconds=301), 300, 3
            )
            await uow.commit()

        assert released == (1, 0)

        async with sessionmaker() as session:
            row = await session.get(OutboxMessageModel, msg_id)
            assert row.status == 'dead'
            assert row.next_retry_at is None
            assert row.finished_at is not None
            assert row.claimed_at is None
            assert row.claimed_by is None

            repo = SqlAlchemyOutboxRepository(lambda: session)
            assert await repo.claim_batch(10, NOW, self.WORKER_B, 3) == []

    async def test_claim_batch_skip_locked(self, sessionmaker):
        """Пока первая сессия удерживает блокировку, второй параллельный захват не видит сообщений."""
        await self._add_messages(sessionmaker, 2)

        async with sessionmaker() as sess_a:
            repo_a = SqlAlchemyOutboxRepository(lambda: sess_a)
            claimed_a = await repo_a.claim_batch(
                10, NOW, self.WORKER_A, self.MAX_ATTEMPTS
            )
            assert len(claimed_a) == 2

            async with sessionmaker() as sess_b:
                repo_b = SqlAlchemyOutboxRepository(lambda: sess_b)
                claimed_b = await repo_b.claim_batch(
                    10, NOW, self.WORKER_B, self.MAX_ATTEMPTS
                )
                assert claimed_b == []


class TestAttemptRepository:
    """Сценарии репозитория попыток: сохранение попыток и получение их по платежу."""

    async def test_add_and_get_by_payment_id(self, sessionmaker):
        """Сохранённая попытка доступна по id платежа."""
        payment = build_payment()
        await insert_payment(sessionmaker, payment)

        attempt = PaymentAttempt.create(
            id=uuid7(),
            payment_id=payment.id,
            attempt_number=1,
            correlation_id='corr',
            created_at=NOW,
        )

        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            await uow.attempt_repository.add(attempt)
            await uow.commit()

        async with sessionmaker() as session:
            repo = SqlAlchemyAttemptRepository(lambda: session)
            attempts = await repo.get_by_payment_id(payment.id)

        assert len(attempts) == 1
        assert attempts[0].attempt_number == 1
        assert attempts[0].status.value == 'created'


class TestWebhookDeliveryRepository:
    """Сценарии репозитория доставок вебхуков: захват просроченных доставок и сохранение обновлений."""

    async def _create_delivery(self, sessionmaker, payment_id) -> WebhookDelivery:
        """Сохраняет новую ожидающую доставку вебхука и возвращает её."""
        delivery = WebhookDelivery.create(
            id=uuid7(),
            payment_id=payment_id,
            event_type='payment.succeeded',
            correlation_id='corr',
            created_at=NOW,
        )
        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            await uow.webhook_delivery_repository.add(delivery)
            await uow.commit()
        return delivery

    async def test_claim_due(self, sessionmaker):
        """Просроченная доставка возвращается методом claim_due."""
        payment = build_payment()
        await insert_payment(sessionmaker, payment)
        delivery = await self._create_delivery(sessionmaker, payment.id)

        async with sessionmaker() as session:
            repo = SqlAlchemyWebhookDeliveryRepository(lambda: session)
            due = await repo.claim_due(10, NOW)

        assert [d.id for d in due] == [delivery.id]

    async def test_claim_due_future_retry_not_included(self, sessionmaker):
        """Доставка, запланированная на будущий повтор, пока не захватывается как просроченная."""
        payment = build_payment()
        await insert_payment(sessionmaker, payment)
        delivery = await self._create_delivery(sessionmaker, payment.id)

        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            loaded = await uow.webhook_delivery_repository.get(delivery.id)
            loaded.schedule_retry(NOW, NOW + timedelta(seconds=10), 500, 'err')
            await uow.webhook_delivery_repository.update(loaded)
            await uow.commit()

        async with sessionmaker() as session:
            repo = SqlAlchemyWebhookDeliveryRepository(lambda: session)
            assert await repo.claim_due(10, NOW) == []

    async def test_update_persists(self, sessionmaker):
        """Обновление доставки сохраняет её новый статус и детали ответа."""
        payment = build_payment()
        await insert_payment(sessionmaker, payment)
        delivery = await self._create_delivery(sessionmaker, payment.id)

        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            loaded = await uow.webhook_delivery_repository.get(delivery.id)
            loaded.mark_success(NOW, 200, '{}')
            await uow.webhook_delivery_repository.update(loaded)
            await uow.commit()

        async with sessionmaker() as session:
            repo = SqlAlchemyWebhookDeliveryRepository(lambda: session)
            updated = await repo.get(delivery.id)

        assert updated is not None
        assert updated.status.value == 'success'
        assert updated.response_code == 200
