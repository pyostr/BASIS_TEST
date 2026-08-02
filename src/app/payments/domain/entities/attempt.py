"""Сущность PaymentAttempt: одно взаимодействие с внешним платёжным шлюзом."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from src.app.payments.domain.exceptions.payment_exceptions import InvalidStateTransition
from src.app.payments.domain.gateway import GatewayResult


class PaymentAttemptStatus(StrEnum):
    """Состояния жизненного цикла PaymentAttempt."""

    CREATED = 'created'
    PROCESSING = 'processing'
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'


class PaymentAttempt:
    """Одна попытка взаимодействия с внешним платёжным шлюзом."""

    _VALID_TRANSITIONS: dict[PaymentAttemptStatus, set[PaymentAttemptStatus]] = {
        PaymentAttemptStatus.CREATED: {PaymentAttemptStatus.PROCESSING},
        PaymentAttemptStatus.PROCESSING: {
            PaymentAttemptStatus.SUCCEEDED,
            PaymentAttemptStatus.FAILED,
        },
        PaymentAttemptStatus.SUCCEEDED: set(),
        PaymentAttemptStatus.FAILED: set(),
    }

    def __init__(
        self,
        *,
        id: UUID,
        payment_id: UUID,
        attempt_number: int,
        status: PaymentAttemptStatus,
        error: str | None,
        gateway_response: dict[str, Any] | None,
        correlation_id: str | None,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        self.id = id
        self.payment_id = payment_id
        self.attempt_number = attempt_number
        self.status = status
        self.error = error
        self.gateway_response = gateway_response
        self.correlation_id = correlation_id
        self.created_at = created_at
        self.updated_at = updated_at

    @classmethod
    def create(
        cls,
        *,
        id: UUID,
        payment_id: UUID,
        attempt_number: int,
        correlation_id: str | None,
        created_at: datetime,
    ) -> PaymentAttempt:
        """Создать новую попытку со статусом CREATED для платежа с меткой времени created_at."""
        return cls(
            id=id,
            payment_id=payment_id,
            attempt_number=attempt_number,
            status=PaymentAttemptStatus.CREATED,
            error=None,
            gateway_response=None,
            correlation_id=correlation_id,
            created_at=created_at,
            updated_at=created_at,
        )

    def start(self, now: datetime) -> None:
        """Переход CREATED -> PROCESSING.

        Предусловия: статус должен быть CREATED.
        Побочные эффекты: устанавливает updated_at.
        """
        self._transition(PaymentAttemptStatus.PROCESSING)
        self.updated_at = now

    def succeed(self, now: datetime, result: GatewayResult) -> None:
        """Переход PROCESSING -> SUCCEEDED.

        Предусловия: статус должен быть PROCESSING.
        Побочные эффекты: сохраняет сырой ответ шлюза, очищает ошибку и
        устанавливает updated_at.
        """
        self._transition(PaymentAttemptStatus.SUCCEEDED)
        self.gateway_response = result.raw
        self.error = None
        self.updated_at = now

    def fail(self, now: datetime, error: str | None) -> None:
        """Переход PROCESSING -> FAILED.

        Предусловия: статус должен быть PROCESSING.
        Побочные эффекты: сохраняет ошибку и устанавливает updated_at.
        """
        self._transition(PaymentAttemptStatus.FAILED)
        self.error = error
        self.updated_at = now

    def _transition(self, target: PaymentAttemptStatus) -> None:
        if target not in self._VALID_TRANSITIONS[self.status]:
            raise InvalidStateTransition(
                details={
                    'current': self.status.value,
                    'target': target.value,
                }
            )
        self.status = target
