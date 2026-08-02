"""Объект-значение IdempotencyKey, накладывающий ограничения printable-ASCII."""

import re

# Printable ASCII (0x21-0x7E) делает ключи безопасными для заголовков и однозначными.
_VALID_KEY_RE = re.compile(r'^[\x21-\x7E]+$')


class IdempotencyKey:
    """Ключ идемпотентности от клиента (внешняя ссылка, не обязательно UUID)."""

    __slots__ = ('value',)

    MAX_LENGTH = 255

    def __init__(self, value: str) -> None:
        if not isinstance(value, str) or not value:
            raise ValueError('Idempotency key must not be empty')

        if len(value) > self.MAX_LENGTH:
            raise ValueError(
                f'Idempotency key must not exceed {self.MAX_LENGTH} characters'
            )

        if not _VALID_KEY_RE.match(value):
            raise ValueError(
                'Idempotency key must contain only printable ASCII (no whitespace)'
            )

        self.value = value

    def __str__(self) -> str:
        return self.value

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IdempotencyKey):
            return NotImplemented
        return self.value == other.value

    def __hash__(self) -> int:
        return hash(self.value)

    def __repr__(self) -> str:
        return f'IdempotencyKey({self.value!r})'
