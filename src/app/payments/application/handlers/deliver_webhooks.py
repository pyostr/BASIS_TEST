"""Прикладной сценарий: доставка вебхуков, срок которых наступил, с политикой повторов."""

import asyncio
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

    Захватывает ожидающие доставки (SKIP LOCKED), отправляет их с ограниченной
    конкуренцией и применяет политику повторов: успех, окончательная неудача
    (попытки исчерпаны) или запланированный повтор с линейным backoff.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        webhook_sender: WebhookSender,
        clock: Clock,
        batch_size: int,
        retry_policy: RetryPolicy,
        concurrency: int = 10,
    ) -> None:
        self.uow_factory = uow_factory
        self.webhook_sender = webhook_sender
        self.clock = clock
        self.batch_size = batch_size
        self.retry_policy = retry_policy
        self.concurrency = concurrency

    @transactional()
    async def handle(self) -> WebhookBatchResult:
        """Захватить и доставить вебхуки, срок которых наступил, применяя политику повторов.

        Сетевые отправки выполняются параллельно с ограничением ``concurrency``,
        чтобы один медленный или недоступный URL не блокировал весь пакет; запись
        результатов в БД остаётся последовательной (сессия не является
        потокобезопасной).

        Возвращает:
            WebhookBatchResult: количество обработанных и неудачных доставок.
        """
        failures = 0
        uow = current_uow()
        deliveries = await uow.webhook_delivery_repository.claim_due(
            self.batch_size,
            self.clock.now(),
        )
        if not deliveries:
            return WebhookBatchResult(processed=0, failures=0)

        payments = await self._load_payments(uow, deliveries)
        results = await self._send_all(deliveries, payments)

        for delivery, result in results:
            if result is None:
                continue
            if await self._record(uow, delivery, result):
                failures += 1
        return WebhookBatchResult(processed=len(deliveries), failures=failures)

    async def _load_payments(self, uow, deliveries) -> dict:
        """Загружает платежи для доставок пакетно, пропуская несуществующие."""
        payments = {}
        for delivery in deliveries:
            if delivery.payment_id not in payments:
                payments[delivery.payment_id] = await uow.payment_repository.get(
                    delivery.payment_id
                )
        return payments

    async def _send_all(self, deliveries, payments) -> list[tuple]:
        """Отправляет вебхуки параллельно, ограничивая конкуренцию семафором.

        Возвращает список ``(delivery, result)`` в том же порядке, что и
        ``deliveries``; ``result`` равен None, если платёж не найден
        (доставка пропускается, не считаясь неудачной).
        """
        semaphore = asyncio.Semaphore(self.concurrency)

        async def send_one(delivery):
            payment = payments.get(delivery.payment_id)
            if payment is None:
                logger.warning(
                    'Webhook %s for payment %s skipped: payment not found (correlation_id=%s)',
                    delivery.id,
                    delivery.payment_id,
                    delivery.correlation_id,
                )
                return delivery, None
            async with semaphore:
                result = await self.webhook_sender.send(payment, delivery)
            return delivery, result

        return await asyncio.gather(*(send_one(d) for d in deliveries))

    async def _record(self, uow, delivery, result) -> bool:
        """Применяет результат доставки (успех/повтор/неудача) и сохраняет его."""
        now = self.clock.now()
        if result.ok:
            delivery.mark_success(now, result.status_code, result.body)
            logger.info(
                'Webhook %s for payment %s delivered (http=%s, correlation_id=%s)',
                delivery.id,
                delivery.payment_id,
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
                    delivery.payment_id,
                    result.status_code,
                    delivery.correlation_id,
                    result.body,
                )
            else:
                logger.warning(
                    'Webhook %s for payment %s delivery failed, retry scheduled '
                    '(attempt=%d/%d, http=%s, correlation_id=%s): %s',
                    delivery.id,
                    delivery.payment_id,
                    delivery.attempt,
                    self.retry_policy.max_attempts,
                    result.status_code,
                    delivery.correlation_id,
                    result.body,
                )

        await uow.webhook_delivery_repository.update(delivery)
        return not result.ok
