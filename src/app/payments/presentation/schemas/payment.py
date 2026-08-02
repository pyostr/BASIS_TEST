"""Pydantic-схемы запросов/ответов для HTTP API платежей."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

Currency = Literal['RUB', 'USD', 'EUR']


class CreatePaymentRequest(BaseModel):
    """Тело запроса на создание платежа.

    Требует положительную сумму не более чем с двумя знаками после запятой,
    поддерживаемую валюту и URL вебхука ``http(s)://`` (валидируется через
    ``_validate_webhook_url``). Ключ идемпотентности передаётся отдельно
    через заголовок ``Idempotency-Key``, а не в теле.
    """

    amount: Decimal = Field(default=10000, gt=0, decimal_places=2)
    currency: Currency
    description: str | None = Field(default='Оплата', max_length=1024)
    metadata: dict[str, Any] = Field(default={'user_id': 100})
    webhook_url: str = 'https://smee.io/QdTdSWuNct1STc1'

    @field_validator('webhook_url')
    @classmethod
    def _validate_webhook_url(cls, value: str) -> str:
        if not value.startswith(('http://', 'https://')):
            raise ValueError('webhook_url must start with http(s)://')
        return value


class PaymentCreatedResponse(BaseModel):
    """Подтверждение, возвращаемое при принятии платежа к обработке."""

    payment_id: UUID
    status: str
    created_at: datetime


class AttemptResponse(BaseModel):
    """Одна попытка обработки платежа, возвращаемая API."""

    attempt_number: int
    status: str
    error: str | None
    gateway_response: dict[str, Any] | None
    created_at: datetime


class PaymentResponse(BaseModel):
    """Полное представление платежа, возвращаемое эндпоинтом получения платежа."""

    payment_id: UUID
    status: str
    amount: Decimal
    currency: str
    description: str | None
    metadata: dict[str, Any]
    idempotency_key: str
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None
    attempts: list[AttemptResponse] | None = None


__all__ = [
    'AttemptResponse',
    'CreatePaymentRequest',
    'PaymentCreatedResponse',
    'PaymentResponse',
]
