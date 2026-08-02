"""Корневой агрегат Payment с явным конечным автоматом и доменными событиями."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from src.app.payments.domain.entities.attempt import PaymentAttempt
from src.app.payments.domain.events.base import DomainEvent
from src.app.payments.domain.events.payment_events import (
    PaymentCreated,
    PaymentFailed,
    PaymentProcessingStarted,
    PaymentSucceeded,
)
from src.app.payments.domain.exceptions.payment_exceptions import InvalidStateTransition
from src.app.payments.domain.gateway import GatewayResult
from src.app.payments.domain.value_objects.idempotency_key import IdempotencyKey
from src.app.payments.domain.value_objects.money import Money


class PaymentStatus(StrEnum):
    """Состояния жизненного цикла Payment."""

    PENDING = 'pending'
    PROCESSING = 'processing'
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'


class Payment:
    """Корневой агрегат с явным конечным автоматом.

    Статус может меняться только через методы ``mark_*``. Каждый переход
    также порождает соответствующее доменное событие.
    """

    _VALID_TRANSITIONS: dict[PaymentStatus, set[PaymentStatus]] = {
        PaymentStatus.PENDING: {PaymentStatus.PROCESSING},
        PaymentStatus.PROCESSING: {PaymentStatus.SUCCEEDED, PaymentStatus.FAILED},
        PaymentStatus.SUCCEEDED: set(),
        PaymentStatus.FAILED: set(),
    }

    def __init__(
        self,
        *,
        id: UUID,
        idempotency_key: IdempotencyKey,
        money: Money,
        description: str | None,
        metadata: dict[str, Any],
        webhook_url: str,
        correlation_id: str | None,
        status: PaymentStatus,
        created_at: datetime,
        processed_at: datetime | None,
        version: int,
    ) -> None:
        self.id = id
        self.idempotency_key = idempotency_key
        self.money = money
        self.description = description
        self.metadata = metadata
        self.webhook_url = webhook_url
        self.correlation_id = correlation_id
        self.status = status
        self.created_at = created_at
        self.processed_at = processed_at
        self.version = version
        self._events: list[DomainEvent] = []
        self._attempts: list[PaymentAttempt] = []

    @classmethod
    def create(
        cls,
        *,
        id: UUID,
        idempotency_key: IdempotencyKey,
        money: Money,
        description: str | None,
        metadata: dict[str, Any],
        webhook_url: str,
        correlation_id: str | None,
        created_at: datetime,
    ) -> Payment:
        """Создать платёж со статусом PENDING и породить событие PaymentCreated.

        Побочные эффекты: версия начинается с 0, processed_at равен None,
        событие PaymentCreated ставится в очередь агрегата.
        """
        payment = cls(
            id=id,
            idempotency_key=idempotency_key,
            money=money,
            description=description,
            metadata=metadata,
            webhook_url=webhook_url,
            correlation_id=correlation_id,
            status=PaymentStatus.PENDING,
            created_at=created_at,
            processed_at=None,
            version=0,
        )
        payment._add_event(
            PaymentCreated(
                aggregate_id=payment.id,
                occurred_at=created_at,
                correlation_id=correlation_id,
                amount=str(money.amount),
                currency=money.currency.value,
                description=description,
                metadata=metadata,
                webhook_url=webhook_url,
                idempotency_key=str(idempotency_key),
                created_at=created_at,
            )
        )
        return payment

    # ------------------------------------------------------------------
    # Конечный автомат
    # ------------------------------------------------------------------
    def mark_processing(self, now: datetime) -> None:
        """Переход PENDING -> PROCESSING.

        Предусловия: статус должен быть PENDING.
        Побочные эффекты: увеличивается версия и порождается событие
        PaymentProcessingStarted.
        """
        self._transition(PaymentStatus.PROCESSING)
        self.version += 1
        self._add_event(
            PaymentProcessingStarted(
                aggregate_id=self.id,
                occurred_at=now,
                correlation_id=self.correlation_id,
            )
        )

    def mark_succeeded(self, now: datetime) -> None:
        """Переход PROCESSING -> SUCCEEDED.

        Предусловия: статус должен быть PROCESSING.
        Побочные эффекты: фиксируется processed_at, увеличивается версия и
        порождается событие PaymentSucceeded.
        """
        self._transition(PaymentStatus.SUCCEEDED)
        self.processed_at = now
        self.version += 1
        self._add_event(
            PaymentSucceeded(
                aggregate_id=self.id,
                occurred_at=now,
                correlation_id=self.correlation_id,
                processed_at=now,
            )
        )

    def mark_failed(self, now: datetime, reason: str | None = None) -> None:
        """Переход PROCESSING -> FAILED.

        Предусловия: статус должен быть PROCESSING.
        Побочные эффекты: фиксируется processed_at, увеличивается версия и
        порождается событие PaymentFailed с причиной неудачи.
        """
        self._transition(PaymentStatus.FAILED)
        self.processed_at = now
        self.version += 1
        self._add_event(
            PaymentFailed(
                aggregate_id=self.id,
                occurred_at=now,
                correlation_id=self.correlation_id,
                reason=reason,
                processed_at=now,
            )
        )

    def _transition(self, target: PaymentStatus) -> None:
        if target not in self._VALID_TRANSITIONS[self.status]:
            raise InvalidStateTransition(
                details={
                    'current': self.status.value,
                    'target': target.value,
                }
            )
        self.status = target

    # ------------------------------------------------------------------
    # Платёжные попытки (дочерние сущности агрегата)
    # ------------------------------------------------------------------
    def hydrate_attempts(self, attempts: list[PaymentAttempt]) -> None:
        """Восстановить уже сохранённые попытки (например, при повторной обработке)."""
        self._attempts = list(attempts)

    @property
    def attempts(self) -> list[PaymentAttempt]:
        """Снимок попыток агрегата без их очистки."""
        return list(self._attempts)

    def begin_attempt(
        self,
        *,
        attempt_id: UUID,
        correlation_id: str | None,
        now: datetime,
    ) -> PaymentAttempt:
        """Начать новую попытку списания.

        Предусловия: платёж должен быть в статусе PROCESSING. Номер попытки
        наследуется от уже накопленных попыток агрегата.
        """
        self._require_processing('begin_attempt')
        number = max((a.attempt_number for a in self._attempts), default=0) + 1
        attempt = PaymentAttempt.create(
            id=attempt_id,
            payment_id=self.id,
            attempt_number=number,
            correlation_id=correlation_id,
            created_at=now,
        )
        attempt.start(now)
        self._attempts.append(attempt)
        return attempt

    def succeed_attempt(self, now: datetime, result: GatewayResult) -> PaymentAttempt:
        """Зафиксировать успешную попытку списания.

        Предусловия: платёж в статусе PROCESSING и уже имеет текущую попытку.
        """
        self._require_processing('succeed_attempt')
        attempt = self._current_attempt()
        attempt.succeed(now, result)
        return attempt

    def fail_attempt(self, now: datetime, error: str | None) -> PaymentAttempt:
        """Зафиксировать неудачную попытку списания.

        Предусловия: платёж в статусе PROCESSING и уже имеет текущую попытку.
        """
        self._require_processing('fail_attempt')
        attempt = self._current_attempt()
        attempt.fail(now, error)
        return attempt

    def _require_processing(self, op: str) -> None:
        if self.status is not PaymentStatus.PROCESSING:
            raise InvalidStateTransition(
                details={
                    'current': self.status.value,
                    'target': op,
                }
            )

    def _current_attempt(self) -> PaymentAttempt:
        if not self._attempts:
            raise InvalidStateTransition(
                details={
                    'current': self.status.value,
                    'target': 'attempt',
                }
            )
        return self._attempts[-1]

    # ------------------------------------------------------------------
    # Доменные события
    # ------------------------------------------------------------------
    def _add_event(self, event: DomainEvent) -> None:
        self._events.append(event)

    @property
    def events(self) -> list[DomainEvent]:
        """Снимок накопленных доменных событий без их очистки."""
        return list(self._events)

    def pull_events(self) -> list[DomainEvent]:
        """Вернуть и очистить список накопленных доменных событий."""
        events, self._events = self._events, []
        return events
