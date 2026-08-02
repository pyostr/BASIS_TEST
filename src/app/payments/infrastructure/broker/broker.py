"""Адаптер брокера RabbitMQ: брокер, топология очередей и регистрация потребителя.

Создаёт exchange, а также очереди main/retry/DLQ (с аргументами TTL и
dead-letter) и подключает входящего потребителя к хэндлеру обработки платежа.
"""

from faststream.middlewares import AckPolicy
from faststream.rabbit import (
    ExchangeType,
    RabbitBroker,
    RabbitExchange,
    RabbitMessage,
    RabbitQueue,
)

from src.app.payments.application.handlers.process_payment import ProcessPaymentHandler
from src.app.payments.infrastructure.broker.consumer import PaymentConsumerHandler
from src.config.settings import Settings


def build_broker(settings: Settings) -> RabbitBroker:
    """Создаёт обработчик брокера RabbitMQ, привязанный к настроенному URL."""
    return RabbitBroker(settings.RABBITMQ_URL, graceful_timeout=5.0)


def build_topology(settings: Settings):
    """Возвращает кортеж (exchange, main_queue, retry_queue, dlq_queue).

    Основная очередь направляет dead-letter в очередь retry, которая задерживает
    через TTL и возвращает dead-letter обратно в основную очередь; DLQ — конечная
    точка назначения.
    """
    exchange = RabbitExchange(
        name=settings.RABBITMQ_EXCHANGE,
        type=ExchangeType(settings.RABBITMQ_EXCHANGE_TYPE),
        durable=True,
    )
    main_queue = RabbitQueue(
        name=settings.RABBITMQ_QUEUE,
        durable=True,
        arguments={
            'x-dead-letter-exchange': settings.RABBITMQ_EXCHANGE,
            'x-dead-letter-routing-key': settings.RABBITMQ_RETRY_QUEUE,
        },
    )
    retry_queue = RabbitQueue(
        name=settings.RABBITMQ_RETRY_QUEUE,
        durable=True,
        arguments={
            'x-message-ttl': settings.RABBITMQ_RETRY_TTL_MS,
            'x-dead-letter-exchange': settings.RABBITMQ_EXCHANGE,
            'x-dead-letter-routing-key': settings.RABBITMQ_ROUTING_KEY,
        },
    )
    dlq_queue = RabbitQueue(name=settings.RABBITMQ_DLQ_QUEUE, durable=True)
    return exchange, main_queue, retry_queue, dlq_queue


async def declare_topology(broker: RabbitBroker, settings: Settings) -> None:
    """Объявляет и привязывает очередь retry (основную очередь объявляет подписчик)."""
    exchange, _main_queue, retry_queue, dlq_queue = build_topology(settings)

    exchange_obj = await broker.declare_exchange(exchange)
    retry_obj = await broker.declare_queue(retry_queue)
    await broker.declare_queue(dlq_queue)

    await retry_obj.bind(exchange_obj, routing_key=settings.RABBITMQ_RETRY_QUEUE)


def register_consumer(
    broker: RabbitBroker,
    process_handler: ProcessPaymentHandler,
    settings: Settings,
) -> PaymentConsumerHandler:
    """Подписывает входящего потребителя на основную очередь с ручной политикой ack.

    Возвращает хэндлер, чтобы вызывающий код мог сохранить на него ссылку.
    """
    exchange, main_queue, _retry_queue, _dlq_queue = build_topology(settings)
    handler = PaymentConsumerHandler(
        process_handler=process_handler,
        broker=broker,
        settings=settings,
    )

    @broker.subscriber(
        queue=main_queue,
        exchange=exchange,
        ack_policy=AckPolicy.MANUAL,
    )
    async def on_payment_created(msg: RabbitMessage) -> None:
        """Передаёт одно входящее сообщение о платеже в хэндлер обработки."""
        await handler.handle(msg)

    return handler


__all__ = [
    'build_broker',
    'build_topology',
    'declare_topology',
    'register_consumer',
]
