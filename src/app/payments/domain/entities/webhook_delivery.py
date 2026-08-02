"""Сущность WebhookDelivery: запись попыток доставки вебхуков в стиле Outbox."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from src.app.payments.domain.exceptions.payment_exceptions import InvalidStateTransition
from src.app.payments.domain.value_objects.retry_policy import RetryPolicy


class WebhookDeliveryStatus(StrEnum):
    """Состояния жизненного цикла доставки вебхука."""

    PENDING = 'pending'
    SUCCESS = 'success'
    FAILED = 'failed'


class WebhookDelivery:
    """Запись попыток доставки вебхуков в стиле Outbox.

    Статус меняется только через ``mark_*``/``schedule_retry``/``record_failure``;
    недопустимые переходы отклоняются конечным автоматом.
    """

    _VALID_TRANSITIONS: dict[WebhookDeliveryStatus, set[WebhookDeliveryStatus]] = {
        WebhookDeliveryStatus.PENDING: {
            WebhookDeliveryStatus.PENDING,
            WebhookDeliveryStatus.SUCCESS,
            WebhookDeliveryStatus.FAILED,
        },
        WebhookDeliveryStatus.SUCCESS: set(),
        WebhookDeliveryStatus.FAILED: set(),
    }

    def __init__(
        self,
        *,
        id: UUID,
        payment_id: UUID,
        event_type: str,
        attempt: int,
        status: WebhookDeliveryStatus,
        response_code: int | None,
        response_body: str | None,
        next_retry_at: datetime | None,
        correlation_id: str | None,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        self.id = id
        self.payment_id = payment_id
        self.event_type = event_type
        self.attempt = attempt
        self.status = status
        self.response_code = response_code
        self.response_body = response_body
        self.next_retry_at = next_retry_at
        self.correlation_id = correlation_id
        self.created_at = created_at
        self.updated_at = updated_at

    @classmethod
    def create(
        cls,
        *,
        id: UUID,
        payment_id: UUID,
        event_type: str,
        correlation_id: str | None,
        created_at: datetime,
    ) -> WebhookDelivery:
        """Создать доставку со статусом PENDING (попытка 1) для события платежа."""
        return cls(
            id=id,
            payment_id=payment_id,
            event_type=event_type,
            attempt=1,
            status=WebhookDeliveryStatus.PENDING,
            response_code=None,
            response_body=None,
            next_retry_at=None,
            correlation_id=correlation_id,
            created_at=created_at,
            updated_at=created_at,
        )

    def mark_success(
        self,
        now: datetime,
        response_code: int | None,
        response_body: str | None,
    ) -> None:
        """Зафиксировать успешную доставку.

        Предусловия: статус должен быть PENDING.
        Побочные эффекты: статус -> SUCCESS, сохраняется ответ, очищается
        next_retry_at и устанавливается updated_at.
        """
        self._transition(WebhookDeliveryStatus.SUCCESS)
        self.response_code = response_code
        self.response_body = response_body
        self.next_retry_at = None
        self.updated_at = now

    def mark_failed(
        self,
        now: datetime,
        response_code: int | None,
        response_body: str | None,
    ) -> None:
        """Зафиксировать терминальную неудачную доставку.

        Предусловия: статус должен быть PENDING.
        Побочные эффекты: статус -> FAILED, сохраняется ответ, очищается
        next_retry_at и устанавливается updated_at.
        """
        self._transition(WebhookDeliveryStatus.FAILED)
        self.response_code = response_code
        self.response_body = response_body
        self.next_retry_at = None
        self.updated_at = now

    def schedule_retry(
        self,
        now: datetime,
        next_retry_at: datetime,
        response_code: int | None,
        response_body: str | None,
    ) -> None:
        """Запланировать ещё одну попытку доставки после неудачи.

        Предусловия: статус должен быть PENDING.
        Побочные эффекты: увеличивается счётчик attempt, статус остаётся
        PENDING, устанавливается next_retry_at и сохраняется ответ.
        """
        self._transition(WebhookDeliveryStatus.PENDING)
        self.attempt += 1
        self.next_retry_at = next_retry_at
        self.response_code = response_code
        self.response_body = response_body
        self.updated_at = now

    def record_failure(
        self,
        now: datetime,
        response_code: int | None,
        response_body: str | None,
        retry_policy: RetryPolicy,
    ) -> None:
        """Зафиксировать неудачную доставку, применяя политику повторов.

        Побочные эффекты: если лимит попыток не исчерпан — планируется повтор
        с backoff; иначе доставка помечается терминально неудачной.
        """
        if retry_policy.should_retry(self.attempt):
            self.schedule_retry(
                now,
                retry_policy.next_retry_at(self.attempt, now),
                response_code,
                response_body,
            )
        else:
            self.mark_failed(now, response_code, response_body)

    def _transition(self, target: WebhookDeliveryStatus) -> None:
        if target not in self._VALID_TRANSITIONS[self.status]:
            raise InvalidStateTransition(
                details={
                    'current': self.status.value,
                    'target': target.value,
                }
            )
        self.status = target
