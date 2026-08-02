"""Прикладной сценарий: чтение одного платежа вместе с его попытками."""

from src.app.payments.application.dto.payment import PaymentDTO
from src.app.payments.application.queries.get_payment import GetPaymentQuery
from src.app.payments.domain.exceptions.payment_exceptions import PaymentNotFound
from src.app.payments.domain.uow import UnitOfWorkFactory
from src.shared.application.transaction import current_uow, transactional


class GetPaymentHandler:
    """Обработчик запросов CQRS."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self.uow_factory = uow_factory

    @transactional(commit=False)
    async def handle(self, query: GetPaymentQuery) -> PaymentDTO:
        """Получить платёж и его попытки по идентификатору.

        Возвращает:
            PaymentDTO: проекция платежа, включая его попытки.

        Исключения:
            PaymentNotFound: платёж с заданным идентификатором не существует.
        """
        uow = current_uow()
        payment = await uow.payment_repository.get(query.payment_id)
        if payment is None:
            raise PaymentNotFound(details={'payment_id': str(query.payment_id)})
        attempts = await uow.attempt_repository.get_by_payment_id(query.payment_id)
        return PaymentDTO.from_payment(payment, attempts=attempts)
