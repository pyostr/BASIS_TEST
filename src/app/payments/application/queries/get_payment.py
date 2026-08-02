"""Прикладной запрос, описывающий, как найти один платёж."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class GetPaymentQuery:
    """Идентифицирует платёж для получения по его идентификатору."""

    payment_id: UUID
