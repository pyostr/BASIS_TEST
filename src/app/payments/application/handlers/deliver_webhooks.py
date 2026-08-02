"""Прикладной сценарий: доставка вебхуков, срок которых наступил, с политикой повторов."""

import logging
from dataclasses import dataclass

from src.app.payments.domain.entities.webhook_delivery import WebhookDeliveryStatus
from src.app.payments.domain.uow import UnitOfWorkFactory
from src.app.payments.domain.value_objects.retry_policy import RetryPolicy
from src.app.payments.domain.webhook_sender import WebhookSender
from src.shared.application.transaction import current_uow, transactional
from src.shared.domain.clock import Clock

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WebhookBatchResult:
    """Количество доставок, обработанных и завершившихся неудачей в одном прогоне батча."""

    processed: int
    failures: int


class DeliverDueWebhooksHandler:
    """Прикладной сценарий: доставка вебхуков, срок которых наступил, с повторами/backoff.

    Захватывает ожидающие доставки (SKIP LOCKED), отправляет каждую и применяет
    политику повторов: успех, окончательная неудача (попытки исчерпаны) или
    запланированный повтор с линейным backoff.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        webhook_sender: WebhookSender,
        clock: Clock,
        batch_size: int,
        retry_policy: RetryPolicy,
    ) -> None:
        self.uow_factory = uow_factory
        self.webhook_sender = webhook_sender
        self.clock = clock
        self.batch_size = batch_size
        self.retry_policy = retry_policy

    @transactional()
    async def handle(self) -> WebhookBatchResult:
        """Захватить и доставить вебхуки, срок которых наступил, применяя политику повторов.

        Возвращает:
            WebhookBatchResult: количество обработанных и неудачных доставок.
        """
        failures = 0
        uow = current_uow()
        deliveries = await uow.webhook_delivery_repository.claim_due(
            self.batch_size,
            self.clock.now(),
        )
        for delivery in deliveries:
            if await self._deliver(uow, delivery):
                failures += 1
        return WebhookBatchResult(processed=len(deliveries), failures=failures)

    async def _deliver(self, uow, delivery) -> bool:
        payment = await uow.payment_repository.get(delivery.payment_id)
        now = self.clock.now()
        if payment is None:
            logger.warning(
                'Webhook %s for payment %s skipped: payment not found (correlation_id=%s)',
                delivery.id,
                delivery.payment_id,
                delivery.correlation_id,
            )
            return False

        result = await self.webhook_sender.send(payment, delivery)

        if result.ok:
            delivery.mark_success(now, result.status_code, result.body)
            logger.info(
                'Webhook %s for payment %s delivered (http=%s, correlation_id=%s)',
                delivery.id,
                payment.id,
                result.status_code,
                delivery.correlation_id,
            )
        else:
            delivery.record_failure(
                now,
                result.status_code,
                result.body,
                self.retry_policy,
            )
            if delivery.status is not WebhookDeliveryStatus.PENDING:
                logger.warning(
                    'Webhook %s for payment %s failed permanently (http=%s, correlation_id=%s): %s',
                    delivery.id,
                    payment.id,
                    result.status_code,
                    delivery.correlation_id,
                    result.body,
                )
            else:
                logger.warning(
                    'Webhook %s for payment %s delivery failed, retry scheduled '
                    '(attempt=%d/%d, http=%s, correlation_id=%s): %s',
                    delivery.id,
                    payment.id,
                    delivery.attempt,
                    self.retry_policy.max_attempts,
                    result.status_code,
                    delivery.correlation_id,
                    result.body,
                )

        await uow.webhook_delivery_repository.update(delivery)
        return not result.ok
