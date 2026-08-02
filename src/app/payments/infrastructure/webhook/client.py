"""HTTP-адаптер, доставляющий подписанные payload вебхуков на URL мерчантов."""

import hashlib
import hmac
import json

import httpx

from src.app.payments.domain.aggregates.payment import Payment
from src.app.payments.domain.entities.webhook_delivery import WebhookDelivery
from src.app.payments.domain.webhook_sender import WebhookSendResult
from src.app.payments.infrastructure.webhook.payload import build_webhook_payload


class WebhookClient:
    """Доставляет payload вебхуков, подписанные с помощью HMAC-SHA256."""

    def __init__(
        self,
        secret: str,
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Настраивает HMAC-секрет и нижележащий HTTP-клиент."""
        self._secret = secret
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def send(
        self,
        payment: Payment,
        delivery: WebhookDelivery,
    ) -> WebhookSendResult:
        """Отправляет POST с подписанным payload вебхука для доставки.

        Сетевые ошибки преобразуются в неуспешный WebhookSendResult, а не
        выбрасываются, чтобы вызывающий код мог запланировать повтор. Тела
        обрезаются до 2048 символов для хранения.
        """
        payload = build_webhook_payload(payment, delivery)
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        signature = hmac.new(self._secret.encode(), body, hashlib.sha256).hexdigest()

        headers = {
            'Content-Type': 'application/json',
            'X-Webhook-Signature': f'sha256={signature}',
            'X-Correlation-ID': delivery.correlation_id or '',
            'X-Event-ID': str(delivery.id),
        }

        try:
            response = await self._client.post(
                payment.webhook_url,
                content=body,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            return WebhookSendResult(ok=False, status_code=None, body=str(exc))

        return WebhookSendResult(
            ok=200 <= response.status_code < 300,
            status_code=response.status_code,
            body=response.text[:2048],
        )


__all__ = ['WebhookClient', 'WebhookSendResult']
