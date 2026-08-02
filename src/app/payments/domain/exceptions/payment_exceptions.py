"""Доменные исключения платежей, сопоставленные со стабильными кодами ошибок."""

from src.shared.exceptions import DomainException


class InvalidStateTransition(DomainException):
    """Возбуждается, когда переход конечного автомата не разрешён."""

    code = 'INVALID_STATE_TRANSITION'


class IdempotencyConflict(DomainException):
    """Возбуждается, когда ключ идемпотентности нельзя переиспользовать."""

    code = 'IDEMPOTENCY_CONFLICT'


class PaymentNotFound(DomainException):
    """Возбуждается, когда запрошенный платёж не существует."""

    code = 'NOT_FOUND'


class InvalidPaymentData(DomainException):
    """Возбуждается, когда входные данные платежа не проходят валидацию."""

    code = 'VALIDATION_ERROR'
