"""Объект-значение Money, валидирующий сумму и валюту."""

from decimal import Decimal, InvalidOperation
from enum import StrEnum


class Currency(StrEnum):
    """Валюты ISO-4217, поддерживаемые для платежей."""

    RUB = 'RUB'
    USD = 'USD'
    EUR = 'EUR'


class Money:
    """Иммутабельный объект-значение: положительная сумма в поддерживаемой валюте."""

    __slots__ = ('_amount', '_currency')

    def __init__(
        self, amount: Decimal | float | int | str, currency: str | Currency
    ) -> None:
        if isinstance(amount, float):
            amount = Decimal(str(amount))
        elif not isinstance(amount, Decimal):
            try:
                amount = Decimal(amount)
            except InvalidOperation as exc:
                raise ValueError(f'Invalid amount: {amount!r}') from exc

        if amount <= 0:
            raise ValueError('Amount must be positive')

        if amount != amount.quantize(Decimal('0.01')):
            raise ValueError('Amount must have at most 2 decimal places')

        self._amount: Decimal = amount
        self._currency: Currency = Currency(currency)

    @property
    def amount(self) -> Decimal:
        return self._amount

    @property
    def currency(self) -> Currency:
        return self._currency

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self._amount == other._amount and self._currency == other._currency

    def __hash__(self) -> int:
        return hash((self._amount, self._currency))

    def __repr__(self) -> str:
        return f'Money({self._amount} {self._currency.value})'
