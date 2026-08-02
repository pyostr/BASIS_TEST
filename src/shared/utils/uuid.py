"""Помощники UUID, включая генерацию упорядоченных по времени UUIDv7."""

import secrets
import time
import uuid


def uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7: упорядочен по времени для лучшей локальности индексов Postgres."""
    timestamp_ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)

    value = (timestamp_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0x2 << 62) | rand_b
    return uuid.UUID(int=value)
