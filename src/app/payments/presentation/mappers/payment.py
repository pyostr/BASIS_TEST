"""Мапперы между DTO приложения и схемами ответов API."""

from src.app.payments.application.dto.payment import AttemptDTO, PaymentDTO
from src.app.payments.presentation.schemas.payment import (
    AttemptResponse,
    PaymentResponse,
)


def to_attempt_response(dto: AttemptDTO) -> AttemptResponse:
    """Преобразует DTO попытки в её схему ответа API."""
    return AttemptResponse(
        attempt_number=dto.attempt_number,
        status=dto.status,
        error=dto.error,
        gateway_response=dto.gateway_response,
        created_at=dto.created_at,
    )


def to_payment_response(dto: PaymentDTO) -> PaymentResponse:
    """Преобразует DTO платежа в его схему ответа API.

    Вложенные попытки преобразуются рекурсивно; попытки ``None`` остаются
    ``None`` в ответе.
    """
    return PaymentResponse(
        payment_id=dto.payment_id,
        status=dto.status,
        amount=dto.amount,
        currency=dto.currency,
        description=dto.description,
        metadata=dto.metadata,
        idempotency_key=dto.idempotency_key,
        webhook_url=dto.webhook_url,
        created_at=dto.created_at,
        processed_at=dto.processed_at,
        attempts=(
            [to_attempt_response(a) for a in dto.attempts]
            if dto.attempts is not None
            else None
        ),
    )


__all__ = ['to_attempt_response', 'to_payment_response']
