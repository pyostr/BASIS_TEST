"""Порт для доставки вебхук-полезных нагрузок мерчантам."""

from dataclasses import dataclass
from typing import Protocol

from src.app.payments.domain.aggregates.payment import Payment
from src.app.payments.domain.entities.webhook_delivery import WebhookDelivery


@dataclass(frozen=True)
class WebhookSendResult:
    """Результат одной попытки доставки вебхука."""

    ok: bool
    status_code: int | None = None
    body: str | None = None


class WebhookSender(Protocol):
    """Порт для доставки вебхук-полезных нагрузок мерчанту.

    Контракт: ``send`` выполняет одну HTTP-доставку и возвращает
    WebhookSendResult; сетевые ошибки должны возвращаться как неуспешный
    результат, чтобы вызывающий код мог применить свою политику повторов.
    """

    async def send(
        self,
        payment: Payment,
        delivery: WebhookDelivery,
    ) -> WebhookSendResult:
        """Доставить вебхук и вернуть результат попытки."""
