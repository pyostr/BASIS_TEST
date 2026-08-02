"""Ограничитель частоты запросов со скользящим окном в памяти."""

import time
from collections import defaultdict


class InMemoryRateLimiter:
    """Ограничитель частоты со скользящим окном, индексируемый произвольными строками и хранящийся в памяти."""

    def __init__(self):
        self._store: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str, limit: int = 5, window_sec: int = 60) -> bool:
        """Возвращает True, если ``key`` совершил не более ``limit`` вызовов за ``window_sec``, иначе False."""
        now = time.time()
        calls = self._store[key]
        # Удаляем истёкшие
        self._store[key] = [t for t in calls if now - t < window_sec]
        if len(self._store[key]) >= limit:
            return False
        self._store[key].append(now)
        return True
