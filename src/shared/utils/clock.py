"""Конкретная реализация системных часов для доменного протокола Clock."""

from datetime import UTC, datetime

from src.shared.domain.clock import Clock


class SystemClock(Clock):
    """Реализация настенных часов для общего порта Clock."""

    def now(self) -> datetime:
        """Возвращает текущее время по настенным часам в UTC."""
        return datetime.now(UTC)


__all__ = ['SystemClock']
