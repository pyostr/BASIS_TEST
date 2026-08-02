"""Тестовые заменители для payments-набора: детерминированные часы, скриптованный
платёжный шлюз, заглушки брокера и webhook-клиента, а также заменитель
consumer-сообщений faststream."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from src.app.payments.domain.gateway import GatewayResult
from src.app.payments.domain.webhook_sender import WebhookSendResult


class FakeClock:
    """Детерминированные часы для тестов."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float = 1.0) -> None:
        self._now += timedelta(seconds=seconds)


@dataclass
class ScriptedGateway:
    """Шлюз, возвращающий заранее заданную последовательность результатов."""

    results: list[GatewayResult] = field(default_factory=list)
    calls: int = 0

    async def charge(self, payment_id, amount, idempotency_key) -> GatewayResult:
        self.calls += 1
        if self.results:
            return self.results.pop(0)
        return GatewayResult(success=True, gateway_id='fake-gw', raw={})


class FakeBroker:
    """Заглушка FastStream-брокера для тестов воркера."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.published: list[tuple[Any, dict]] = []
        self.correlation_ids: list[str] = []

    async def publish(self, message, **kwargs) -> None:
        if self.fail:
            raise RuntimeError('broker is down')
        self.published.append((message, kwargs))
        self.correlation_ids.append(kwargs.get('correlation_id'))


class FakeWebhookClient:
    """Webhook-клиент, отвечающий скриптованной последовательностью ответов (status, body)."""

    def __init__(self, responses: list[tuple[int, str]] | None = None) -> None:
        self._responses = list(responses or [(200, '{}')])
        self.sent: list[tuple[Any, int]] = []

    async def send(self, payment, delivery):
        self.sent.append((delivery.id, delivery.attempt))
        code, text = self._responses.pop(0)
        return WebhookSendResult(ok=200 <= code < 300, status_code=code, body=text)


class FakeMessage:
    """Минимальный заменитель RabbitMessage из faststream."""

    def __init__(
        self,
        body: Any = None,
        headers: dict[str, Any] | None = None,
        message_id: str = 'msg-1',
        correlation_id: str | None = 'corr-1',
    ) -> None:
        self.body = (
            body
            if isinstance(body, bytes)
            else json.dumps(body, ensure_ascii=False).encode()
        )
        self.headers = headers or {}
        self.message_id = message_id
        self.correlation_id = correlation_id
        self.acked = False
        self.nacked = False
        self.nack_requeue: bool | None = None

    async def ack(self) -> None:
        self.acked = True

    async def nack(self, requeue: bool = False) -> None:
        self.nacked = True
        self.nack_requeue = requeue

    async def decode(self) -> Any:
        try:
            return json.loads(self.body.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f'invalid message body: {exc}') from exc


__all__ = ['FakeBroker', 'FakeClock', 'FakeMessage', 'ScriptedGateway']
