"""Неизменяемая команда, описывающая создание нового платежа."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class CreatePaymentCommand:
    """Входные данные для создания платежа: ключ идемпотентности, сумма, валюта и эндпоинт вебхука."""

    idempotency_key: str
    amount: Decimal
    currency: str
    description: str | None
    metadata: dict[str, Any]
    webhook_url: str
    correlation_id: str | None
