"""Прикладной сценарий: провести платёж через шлюз до терминального состояния."""

import logging

from src.app.payments.application.commands.process_payment import (
    PaymentProcessingOutcome,
    PaymentProcessingResult,
    ProcessPaymentCommand,
)
from src.app.payments.domain.aggregates.payment import PaymentStatus
from src.app.payments.domain.entities.webhook_delivery import WebhookDelivery
from src.app.payments.domain.gateway import PaymentGateway
from src.app.payments.domain.uow import UnitOfWorkFactory
from src.shared.application.transaction import current_uow, transactional
from src.shared.domain.clock import Clock
from src.shared.utils.uuid import uuid7

logger = logging.getLogger(__name__)


class ProcessPaymentHandler:
    """Прикладной сценарий: довести сообщение PaymentCreated до терминального состояния.

    Захватывает платёж (pending -> processing), вызывает шлюз, финализирует
    платёж (succeeded/failed), фиксирует попытку и подготавливает доставку вебхука.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        gateway: PaymentGateway,
        clock: Clock,
    ) -> None:
        self.uow_factory = uow_factory
        self.gateway = gateway
        self.clock = clock

    @transactional()
    async def handle(self, command: ProcessPaymentCommand) -> PaymentProcessingResult:
        """Захватить и обработать платёж со статусом PENDING через шлюз.

        Предусловия: платёж должен быть в статусе PENDING. Он захватывается
        атомарно (pending -> processing); при конфликте версий обработчик
        возвращает CLAIM_CONFLICT без побочных эффектов.

        Побочные эффекты: финализирует платёж (succeeded/failed), фиксирует
        PaymentAttempt, подготавливает WebhookDelivery и делает коммит в одной
        транзакции.

        Возвращает:
            PaymentProcessingResult: результат плюс идентификатор шлюза или ошибка.
        """
        uow = current_uow()
        payment = await uow.payment_repository.get(command.payment_id)
        if payment is None:
            return PaymentProcessingResult(PaymentProcessingOutcome.NOT_FOUND)

        if payment.status in (PaymentStatus.SUCCEEDED, PaymentStatus.FAILED):
            return PaymentProcessingResult(PaymentProcessingOutcome.ALREADY_TERMINAL)

        if payment.status is not PaymentStatus.PENDING:
            return PaymentProcessingResult(PaymentProcessingOutcome.NOT_PENDING)

        started_at = self.clock.now()
        expected_version = payment.version
        expected_status = payment.status
        payment.mark_processing(started_at)
        claimed = await uow.payment_repository.begin_processing(
            payment.id, expected_version, expected_status
        )
        if not claimed:
            return PaymentProcessingResult(PaymentProcessingOutcome.CLAIM_CONFLICT)

        existing_attempts = await uow.attempt_repository.get_by_payment_id(payment.id)
        payment.hydrate_attempts(existing_attempts)
        attempt = payment.begin_attempt(
            attempt_id=uuid7(),
            correlation_id=command.correlation_id,
            now=started_at,
        )
        await uow.attempt_repository.add(attempt)

        result = await self.gateway.charge(
            payment.id,
            payment.money,
            str(payment.idempotency_key),
        )

        finished_at = self.clock.now()
        expected_processing_version = payment.version
        expected_processing_status = payment.status
        if result.success:
            payment.succeed_attempt(finished_at, result)
            payment.mark_succeeded(finished_at)
            claimed = await uow.payment_repository.mark_succeeded(
                payment.id,
                expected_processing_version,
                expected_processing_status,
                finished_at,
            )
            event_type = 'payment.succeeded'
            outcome = PaymentProcessingOutcome.SUCCEEDED
        else:
            payment.fail_attempt(finished_at, result.error)
            payment.mark_failed(finished_at, result.error)
            claimed = await uow.payment_repository.mark_failed(
                payment.id,
                expected_processing_version,
                expected_processing_status,
                finished_at,
            )
            event_type = 'payment.failed'
            outcome = PaymentProcessingOutcome.FAILED

        if not claimed:
            raise RuntimeError(f'Version conflict finalizing payment {payment.id}')

        await uow.attempt_repository.update(attempt)

        delivery = WebhookDelivery.create(
            id=uuid7(),
            payment_id=payment.id,
            event_type=event_type,
            correlation_id=command.correlation_id,
            created_at=finished_at,
        )
        await uow.webhook_delivery_repository.add(delivery)

        if outcome is PaymentProcessingOutcome.SUCCEEDED:
            logger.info(
                'Payment %s processed: succeeded (correlation_id=%s, attempt=%d, gateway=%s)',
                payment.id,
                command.correlation_id,
                attempt.attempt_number,
                result.gateway_id,
            )
        else:
            logger.warning(
                'Payment %s processed: failed (correlation_id=%s, attempt=%d, error=%s, raw=%s)',
                payment.id,
                command.correlation_id,
                attempt.attempt_number,
                result.error,
                result.raw,
            )

        return PaymentProcessingResult(
            outcome=outcome,
            gateway_id=result.gateway_id or result.error,
        )
