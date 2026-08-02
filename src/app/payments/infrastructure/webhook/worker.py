"""Воркер доставки вебхуков: тонкий цикл опроса, делегирующий прикладному хэндлеру."""

import asyncio
import logging

from src.app.payments.application.handlers.deliver_webhooks import (
    DeliverDueWebhooksHandler,
    WebhookBatchResult,
)
from src.runtime.observability.metrics import metrics

logger = logging.getLogger(__name__)


class WebhookWorker:
    """Тонкий цикл опроса: делегирует доставку в DeliverDueWebhooksHandler."""

    def __init__(
        self,
        deliver_handler: DeliverDueWebhooksHandler,
        poll_interval: float,
    ) -> None:
        self._deliver_handler = deliver_handler
        self._poll_interval = poll_interval

    async def run(self) -> None:
        """Цикл опроса: обрабатывает один пакет, затем спит в течение интервала опроса.

        Исключения пакета логируются и проглатываются, чтобы кратковременный сбой
        не останавливал цикл; отмена распространяется для корректного завершения.
        """
        while True:
            metrics.worker_cycles_total.labels(worker='webhook').inc()
            try:
                await self.process_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('Webhook worker batch failed')
            await asyncio.sleep(self._poll_interval)

    async def process_once(self) -> WebhookBatchResult:
        """Выполняет один проход доставки и возвращает результат."""
        result = await self._deliver_handler.handle()
        metrics.webhook_failures_total.inc(result.failures)
        return result


__all__ = ['WebhookWorker']
