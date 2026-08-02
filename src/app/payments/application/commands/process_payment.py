"""Неизменяемые команды и результаты сценария обработки платежа."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class PaymentProcessingOutcome(StrEnum):
    """Возможные результаты обработки сообщения о платеже."""

    SUCCEEDED = 'succeeded'
    FAILED = 'failed'
    ALREADY_TERMINAL = 'already_terminal'
    NOT_FOUND = 'not_found'
    NOT_PENDING = 'not_pending'
    CLAIM_CONFLICT = 'claim_conflict'


@dataclass(frozen=True)
class ProcessPaymentCommand:
    """Входные данные для обработки платежа: идентификатор платежа и correlation id."""

    payment_id: UUID
    correlation_id: str | None


@dataclass(frozen=True)
class PaymentProcessingResult:
    """Результат обработки, при необходимости с идентификатором транзакции шлюза."""

    outcome: PaymentProcessingOutcome
    gateway_id: str | None = None


__all__ = [
    'PaymentProcessingOutcome',
    'PaymentProcessingResult',
    'ProcessPaymentCommand',
]
