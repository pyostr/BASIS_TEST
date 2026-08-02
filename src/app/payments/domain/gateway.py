"""Порты для списания платежей через внешний платёжный шлюз."""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from src.app.payments.domain.value_objects.money import Money


@dataclass(frozen=True)
class GatewayResult:
    """Результат вызова списания в шлюзе: флаг успеха и детали шлюза."""

    success: bool
    gateway_id: str | None = None
    error: str | None = None
    raw: dict[str, Any] | None = None


class PaymentGateway(Protocol):
    """Порт к внешнему платёжному шлюзу.

    Контракт: ``charge`` выполняет одну попытку платежа и всегда возвращает
    GatewayResult. Сбои на транспортном уровне должны отражаться как
    неуспешный результат (или выбрасываться), чтобы вызывающий код мог
    зафиксировать попытку и повторить её.
    """

    async def charge(
        self,
        payment_id: UUID,
        amount: Money,
        idempotency_key: str,
    ) -> GatewayResult:
        """Списать платёж. Возвращает бизнес-результат (успех или неудачу)."""
        ...
