"""HTTP-эндпоинты платежей (API v1).

Реализует создание и получение платежей на основе обработчиков
команд/запросов приложения, извлекаемых из DI-контейнера. Каждый маршрут
защищён зависимостью ``X-API-Key``.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from src.app.payments.application.commands.create_payment import CreatePaymentCommand
from src.app.payments.application.queries.get_payment import GetPaymentQuery
from src.app.payments.presentation.api.v1.payments.dependencies import require_api_key
from src.app.payments.presentation.mappers.payment import to_payment_response
from src.app.payments.presentation.schemas.payment import (
    CreatePaymentRequest,
    PaymentCreatedResponse,
    PaymentResponse,
)

router = APIRouter(
    prefix='/payments',
    tags=['payments'],
    dependencies=[Depends(require_api_key)],
)


def _container(request: Request):
    return request.app.state.payments_container


@router.post(
    '',
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PaymentCreatedResponse,
    summary='Create a payment',
)
async def create_payment(
    request: Request,
    body: CreatePaymentRequest,
    idempotency_key: str = Header(..., alias='Idempotency-Key'),
) -> PaymentCreatedResponse:
    """Создаёт платёж и принимает его к обработке.

    Идемпотентен по заголовку ``Idempotency-Key``: повторная отправка того же
    ключа возвращает уже созданный платёж вместо нового. Отвечает
    202 Accepted, поскольку обработка асинхронна.
    Требуется валидный ``X-API-Key`` (обеспечивается зависимостью маршрутизатора).
    """
    command = CreatePaymentCommand(
        idempotency_key=idempotency_key,
        amount=body.amount,
        currency=body.currency,
        description=body.description,
        metadata=body.metadata,
        webhook_url=body.webhook_url,
        correlation_id=getattr(request.state, 'correlation_id', None),
    )
    dto = await _container(request).create_payment_handler().handle(command)
    return PaymentCreatedResponse(
        payment_id=dto.payment_id,
        status=dto.status,
        created_at=dto.created_at,
    )


@router.get(
    '/{payment_id}',
    response_model=PaymentResponse,
    summary='Get a payment',
)
async def get_payment(
    request: Request,
    payment_id: UUID,
) -> PaymentResponse:
    """Получает платёж по идентификатору, включая его попытки обработки.

    Возвращает 404, когда ни один платёж не соответствует ``payment_id``.
    Требуется валидный ``X-API-Key`` (обеспечивается зависимостью маршрутизатора).
    """
    dto = (
        await _container(request)
        .get_payment_handler()
        .handle(GetPaymentQuery(payment_id=payment_id))
    )
    return to_payment_response(dto)


__all__ = ['router']
