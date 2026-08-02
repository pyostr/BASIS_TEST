"""Входящий адаптер RabbitMQ для сообщений PaymentCreated.

Тонкий потребитель, который декодирует сообщения, делегирует обработку
прикладному хэндлеру и реализует протокол ack/nack + retry/DLQ
(см. PaymentConsumerHandler).
"""

import json
import logging
import time
from typing import Any
from uuid import UUID

from faststream.rabbit import RabbitBroker, RabbitMessage, RabbitQueue

from src.app.payments.application.commands.process_payment import (
    PaymentProcessingOutcome,
    ProcessPaymentCommand,
)
from src.app.payments.application.handlers.process_payment import ProcessPaymentHandler
from src.config.settings import Settings
from src.runtime.observability.metrics import metrics

logger = logging.getLogger(__name__)

PAYMENT_CREATED = 'PaymentCreated'


class PaymentConsumerHandler:
    """Тонкий входящий адаптер RabbitMQ для сообщений PaymentCreated.

    Декодирует сообщение, делегирует бизнес-процесс в ProcessPaymentHandler
    и обрабатывает ack/nack и маршрутизацию в DLQ. Бизнес-логики здесь нет.
    """

    def __init__(
        self,
        process_handler: ProcessPaymentHandler,
        broker: RabbitBroker,
        settings: Settings,
    ) -> None:
        self._process_handler = process_handler
        self._broker = broker
        self._settings = settings

    async def handle(self, msg: RabbitMessage) -> None:
        """Ack при успехе, nack без повторной постановки в очередь при ошибке (запускает маршрутизацию в DLQ).

        nack(requeue=False) отправляет сообщение в dead-letter exchange,
        поэтому повторы и финальное размещение в DLQ управляются топологией очередей.
        """
        try:
            await self._route(msg)
        except Exception:
            logger.exception(
                'Payment consumer error (message_id=%s); scheduling retry',
                msg.message_id,
            )
            metrics.payments_retry_count.inc()
            await msg.nack(requeue=False)
        else:
            await msg.ack()

    async def _route(self, msg: RabbitMessage) -> None:
        # Сообщения с неразбираемым телом сразу уходят в DLQ, а не
        # повторяются, поскольку повторная доставка их никогда не исправит.
        try:
            body: Any = await msg.decode()
        except (ValueError, TypeError, json.JSONDecodeError):
            logger.warning('Invalid message body; sending to DLQ')
            await self._send_to_dlq(msg)
            return

        if not isinstance(body, dict):
            logger.warning('Non-object message body; sending to DLQ')
            await self._send_to_dlq(msg)
            return

        if body.get('event_type') != PAYMENT_CREATED:
            logger.warning(
                'Unexpected event_type=%r; acking',
                body.get('event_type'),
            )
            return

        retry_count = self._rejected_count(msg.headers.get('x-death'))
        if retry_count >= self._settings.RABBITMQ_MAX_RETRIES:
            logger.warning(
                'Message %s exhausted %d retries; sending to DLQ',
                msg.message_id,
                retry_count,
            )
            await self._send_to_dlq(msg)
            return

        await self._process(body)

    async def _process(self, body: dict[str, Any]) -> None:
        payment_id = UUID(body['aggregate_id'])
        correlation_id = body.get('correlation_id')

        metrics.payments_inflight.inc()
        start = time.perf_counter()
        try:
            result = await self._process_handler.handle(
                ProcessPaymentCommand(
                    payment_id=payment_id,
                    correlation_id=correlation_id,
                )
            )
        finally:
            metrics.payments_inflight.dec()
            metrics.payments_processing_duration_seconds.observe(
                time.perf_counter() - start
            )

        if result.outcome is PaymentProcessingOutcome.SUCCEEDED:
            metrics.payments_total.labels(status='succeeded').inc()
            logger.info(
                'Payment %s finalized: succeeded (gateway=%s)',
                payment_id,
                result.gateway_id,
            )
        elif result.outcome is PaymentProcessingOutcome.FAILED:
            metrics.payments_total.labels(status='failed').inc()
            logger.info(
                'Payment %s finalized: failed (gateway=%s)',
                payment_id,
                result.gateway_id,
            )

    async def _send_to_dlq(self, msg: RabbitMessage) -> None:
        await self._broker.publish(
            msg.body,
            queue=RabbitQueue(name=self._settings.RABBITMQ_DLQ_QUEUE, durable=True),
            headers=msg.headers,
            correlation_id=msg.correlation_id,
        )

    @staticmethod
    def _rejected_count(x_death: Any) -> int:
        # RabbitMQ записывает каждую отклонённую доставку в заголовок x-death;
        # суммируем счётчики, чтобы определить, исчерпал ли сообщение свои повторы.
        if not isinstance(x_death, list):
            return 0
        return sum(
            int(entry.get('count', 1))
            for entry in x_death
            if isinstance(entry, dict) and entry.get('reason') == 'rejected'
        )


__all__ = ['PAYMENT_CREATED', 'PaymentConsumerHandler']
