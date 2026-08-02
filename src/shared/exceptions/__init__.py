"""Публичные типы исключений, переэкспортируемые для использования по всему приложению."""

from src.shared.exceptions.base import (
    ConflictError,
    DomainException,
    NotFoundError,
    ValidationError,
)

__all__ = [
    'ConflictError',
    'DomainException',
    'NotFoundError',
    'ValidationError',
]
