"""Прикладной сценарий: атомарно создать платёж вместе с его событием outbox."""

from src.app.payments.application.commands.create_payment import CreatePaymentCommand
from src.app.payments.application.dto.payment import PaymentDTO
from src.app.payments.domain.aggregates.payment import Payment
from src.app.payments.domain.exceptions.payment_exceptions import (
    IdempotencyConflict,
    InvalidPaymentData,
)
from src.app.payments.domain.uow import UnitOfWorkFactory
from src.app.payments.domain.value_objects.idempotency_key import IdempotencyKey
from src.app.payments.domain.value_objects.money import Money
from src.shared.application.transaction import current_uow, transactional
from src.shared.domain.clock import Clock
from src.shared.utils.uuid import uuid7


class CreatePaymentHandler:
    """Обработчик команд CQRS. Создаёт Payment(pending) + Outbox(PaymentCreated) в одной транзакции."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self.uow_factory = uow_factory
        self.clock = clock

    @transactional()
    async def handle(self, command: CreatePaymentCommand) -> PaymentDTO:
        """Создать платёж со статусом PENDING и подготовить его событие outbox PaymentCreated.

        Возвращает существующий платёж, если ключ идемпотентности уже был использован.

        Исключения:
            InvalidPaymentData: ключ идемпотентности или сумма недействительны.
            IdempotencyConflict: вставка была отклонена, но платёж не удалось
                перезагрузить по заданному ключу.
        """
        now = self.clock.now()
        uow = current_uow()

        try:
            idempotency_key = IdempotencyKey(command.idempotency_key)
            money = Money(command.amount, command.currency)
        except ValueError as exc:
            raise InvalidPaymentData(details={'message': str(exc)}) from exc

        payment = Payment.create(
            id=uuid7(),
            idempotency_key=idempotency_key,
            money=money,
            description=command.description,
            metadata=command.metadata,
            webhook_url=command.webhook_url,
            correlation_id=command.correlation_id,
            created_at=now,
        )

        inserted = await uow.payment_repository.try_insert(payment)
        if inserted is None:
            existing = await uow.payment_repository.get_by_idempotency_key(
                command.idempotency_key
            )
            if existing is None:
                raise IdempotencyConflict(
                    details={'idempotency_key': command.idempotency_key}
                )
            return PaymentDTO.from_payment(existing)

        await uow.collect_events(payment.pull_events())
        return PaymentDTO.from_payment(payment)
