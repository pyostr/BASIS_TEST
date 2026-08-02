"""Базовая иерархия исключений приложения со стабильным машиночитаемым ``code``.

Доменные исключения сопоставляются с HTTP-статусами через свой ``code`` и могут нести структурированные ``details``.
"""

from typing import Any


class DomainException(Exception):
    """Базовый класс всех доменных ошибок; несёт стабильный ``code`` и опциональные структурированные ``details``."""

    code: str = 'DOMAIN_ERROR'

    def __init__(self, details: dict[str, Any] | None = None):
        self.details = details or {}
        super().__init__(self.code)


class NotFoundError(DomainException):
    """Возникает, когда запрошенный ресурс не существует (соответствует HTTP 404)."""

    code = 'NOT_FOUND'


class ConflictError(DomainException):
    """Возникает, когда ресурс конфликтует с существующим состоянием (соответствует HTTP 409)."""

    code = 'ALREADY_EXISTS'


class ValidationError(DomainException):
    """Возникает, когда проверка бизнес-правил не пройдена (соответствует HTTP 422)."""

    code = 'VALIDATION_ERROR'
