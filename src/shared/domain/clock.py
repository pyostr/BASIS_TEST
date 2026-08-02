"""Абстракция порта часов, отделяющая код приложения от реализаций настенных часов."""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """Протокол источника времени, возвращающего текущую дату и время."""

    def now(self) -> datetime:
        """Возвращает текущее время по настенным часам."""
