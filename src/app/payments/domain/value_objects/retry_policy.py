"""Объект-значение RetryPolicy: политика повторов доставки вебхуков с backoff."""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class RetryPolicy:
    """Правила повторов: максимальное число попыток и базовый backoff.

    Инкапсулирует бизнес-правило «сколько раз и с какой задержкой повторять
    доставку вебхука», чтобы оно жило в домене, а не в прикладном слое.
    """

    max_attempts: int
    base_delay: float

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError('max_attempts must be at least 1')
        if self.base_delay < 0:
            raise ValueError('base_delay must be non-negative')

    def should_retry(self, attempt: int) -> bool:
        """Вернуть True, если попытка ``attempt`` ещё не исчерпала лимит повторов."""
        return attempt < self.max_attempts

    def next_retry_at(self, attempt: int, now: datetime) -> datetime:
        """Вернуть время следующей попытки после неудачи текущей ``attempt``.

        Задержка растёт линейно: base_delay * номер неудачной попытки.
        """
        return now + timedelta(seconds=self.base_delay * attempt)


__all__ = ['RetryPolicy']
