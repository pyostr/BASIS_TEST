"""Помощники времени, возвращающие UTC-даты с учётом часового пояса."""

from datetime import UTC, datetime


def utcnow():
    """Возвращает текущую UTC-дату и время (с учётом часового пояса)."""
    return datetime.now(UTC)
