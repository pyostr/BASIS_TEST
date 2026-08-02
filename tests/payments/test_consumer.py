"""Тесты RabbitMQ consumer-а платежей: обработка шлюзом, семантика ack/nack,
обработка повторов и маршрутизация в DLQ."""

from sqlalchemy import text
from tests.payments.fakes import FakeBroker, FakeClock, FakeMessage, ScriptedGateway
from tests.payments.helpers import (
    build_payment,
    insert_payment,
    payment_created_payload,
)

from src.app.payments.application.handlers.process_payment import ProcessPaymentHandler
from src.app.payments.domain.aggregates.payment import PaymentStatus
from src.app.payments.domain.gateway import GatewayResult
from src.app.payments.infrastructure.broker.consumer import PaymentConsumerHandler
from src.app.payments.infrastructure.repositories.payment import (
    SqlAlchemyPaymentRepository,
)
from src.app.payments.infrastructure.uow import SqlAlchemyPaymentsUnitOfWork
from src.config.settings import Settings


class RaisingGateway:
    """Заменитель шлюза, который всегда бросает исключение, имитируя сбой инфраструктуры."""

    async def charge(self, *args, **kwargs):
        raise RuntimeError('gateway timeout')


def _handler(sessionmaker, gateway, broker=None, clock=None):
    """Создаёт PaymentConsumerHandler, подключённый к заданным шлюзу, брокеру и часам."""
    process_handler = ProcessPaymentHandler(
        lambda: SqlAlchemyPaymentsUnitOfWork(sessionmaker),
        gateway,
        clock or FakeClock(),
    )
    return PaymentConsumerHandler(
        process_handler,
        broker or FakeBroker(),
        Settings(),
    )


async def _load_payment(sessionmaker, payment_id):
    """Перезагружает агрегат платежа из базы данных."""
    async with sessionmaker() as session:
        return await SqlAlchemyPaymentRepository(lambda: session).get(payment_id)


async def _count(sessionmaker, table: str) -> int:
    """Возвращает количество строк в указанной таблице."""
    async with sessionmaker() as session:
        result = await session.execute(text(f'SELECT count(*) FROM {table}'))
        return result.scalar_one()


class TestConsumer:
    """Сценарии consumer: переходы успеха/неудачи шлюза, семантика ack/nack, повторы и маршрутизация в DLQ."""

    async def test_gateway_success(self, sessionmaker):
        """Успех шлюза переводит платёж в SUCCEEDED и фиксирует попытку и доставку вебхука."""
        payment = build_payment()
        await insert_payment(sessionmaker, payment)
        gateway = ScriptedGateway(
            [GatewayResult(success=True, gateway_id='gw-1', raw={'txn': '1'})]
        )
        handler = _handler(sessionmaker, gateway)

        await handler._route(FakeMessage(body=payment_created_payload(payment)))

        loaded = await _load_payment(sessionmaker, payment.id)
        assert loaded is not None
        assert loaded.status is PaymentStatus.SUCCEEDED
        assert loaded.processed_at is not None
        assert gateway.calls == 1

        async with sessionmaker() as session:
            attempt = await session.execute(
                text('SELECT status FROM payment_attempts WHERE payment_id = :id'),
                {'id': payment.id},
            )
            assert attempt.scalar_one() == 'succeeded'
            delivery = await session.execute(
                text(
                    'SELECT event_type FROM webhook_deliveries WHERE payment_id = :id'
                ),
                {'id': payment.id},
            )
            assert delivery.scalar_one() == 'payment.succeeded'

    async def test_success_acks_message(self, sessionmaker):
        """Успешно обработанное сообщение подтверждается (ack)."""
        payment = build_payment()
        await insert_payment(sessionmaker, payment)
        handler = _handler(
            sessionmaker,
            ScriptedGateway([GatewayResult(success=True, gateway_id='gw-1', raw={})]),
        )
        message = FakeMessage(body=payment_created_payload(payment))

        await handler.handle(message)

        assert message.acked is True

    async def test_gateway_failure(self, sessionmaker):
        """Отказ шлюза переводит платёж в FAILED и фиксирует неудачную попытку и вебхук."""
        payment = build_payment()
        await insert_payment(sessionmaker, payment)
        gateway = ScriptedGateway([GatewayResult(success=False, error='declined')])
        handler = _handler(sessionmaker, gateway)

        await handler._route(FakeMessage(body=payment_created_payload(payment)))

        loaded = await _load_payment(sessionmaker, payment.id)
        assert loaded is not None
        assert loaded.status is PaymentStatus.FAILED

        async with sessionmaker() as session:
            attempt = await session.execute(
                text(
                    'SELECT status, error FROM payment_attempts WHERE payment_id = :id'
                ),
                {'id': payment.id},
            )
            status, error = attempt.one()
            assert status == 'failed'
            assert error == 'declined'
            delivery = await session.execute(
                text(
                    'SELECT event_type FROM webhook_deliveries WHERE payment_id = :id'
                ),
                {'id': payment.id},
            )
            assert delivery.scalar_one() == 'payment.failed'

    async def test_repeat_delivery_acks_without_gateway_call(self, sessionmaker):
        """Повторная доставка того же сообщения идемпотентна: подтверждается без второго вызова шлюза."""
        payment = build_payment()
        await insert_payment(sessionmaker, payment)
        gateway = ScriptedGateway(
            [GatewayResult(success=True, gateway_id='gw-1', raw={})]
        )
        handler = _handler(sessionmaker, gateway)
        message = FakeMessage(body=payment_created_payload(payment))

        await handler._route(message)
        await handler._route(message)

        assert gateway.calls == 1
        assert await _count(sessionmaker, 'payment_attempts') == 1

    async def test_missing_payment_acks(self, sessionmaker):
        """Сообщение для неизвестного платежа подтверждается (ack) без побочных эффектов."""
        payment = build_payment()
        gateway = ScriptedGateway()
        handler = _handler(sessionmaker, gateway)

        await handler._route(FakeMessage(body=payment_created_payload(payment)))

        assert gateway.calls == 0
        assert await _count(sessionmaker, 'payments') == 0

    async def test_infrastructure_error_nacks(self, sessionmaker):
        """Сбой инфраструктуры отправляет nack без requeue и оставляет платёж нетронутым."""
        payment = build_payment()
        await insert_payment(sessionmaker, payment)
        handler = _handler(sessionmaker, RaisingGateway())
        message = FakeMessage(body=payment_created_payload(payment))

        await handler.handle(message)

        assert message.nacked is True
        assert message.nack_requeue is False
        loaded = await _load_payment(sessionmaker, payment.id)
        assert loaded is not None
        assert loaded.status is PaymentStatus.PENDING
        assert loaded.version == 0
        assert await _count(sessionmaker, 'payment_attempts') == 0
        assert await _count(sessionmaker, 'webhook_deliveries') == 0

    async def test_retries_exhausted_sends_to_dlq(self, sessionmaker):
        """Сообщение с исчерпанными попытками повтора направляется в DLQ без обработки."""
        payment = build_payment()
        await insert_payment(sessionmaker, payment)
        gateway = ScriptedGateway()
        broker = FakeBroker()
        handler = _handler(sessionmaker, gateway, broker=broker)
        message = FakeMessage(
            body=payment_created_payload(payment),
            headers={'x-death': [{'reason': 'rejected', 'count': 3}]},
        )

        await handler._route(message)

        assert gateway.calls == 0
        assert len(broker.published) == 1
        _, kwargs = broker.published[0]
        assert kwargs['queue'].name == Settings().RABBITMQ_DLQ_QUEUE

    async def test_invalid_json_sends_to_dlq(self, sessionmaker):
        """Нераспознаваемое тело сообщения направляется в DLQ."""
        broker = FakeBroker()
        handler = _handler(sessionmaker, ScriptedGateway(), broker=broker)

        await handler._route(FakeMessage(body=b'not-json'))

        assert len(broker.published) == 1
        _, kwargs = broker.published[0]
        assert kwargs['queue'].name == Settings().RABBITMQ_DLQ_QUEUE

    async def test_unknown_event_type_acks(self, sessionmaker):
        """Неизвестный тип события подтверждается (ack) и игнорируется."""
        broker = FakeBroker()
        handler = _handler(sessionmaker, ScriptedGateway(), broker=broker)

        await handler._route(FakeMessage(body={'event_type': 'SomethingElse'}))

        assert broker.published == []
