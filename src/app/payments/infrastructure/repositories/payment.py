"""SQLAlchemy-репозиторий для платежей (адаптер порта домена).

Реализует переходы состояний с оптимистичной блокировкой через проверку
версии и идемпотентную вставку через ON CONFLICT DO NOTHING.
"""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.payments.domain.aggregates.payment import Payment, PaymentStatus
from src.app.payments.infrastructure.mappers.payment import to_domain
from src.app.payments.infrastructure.models.payment import PaymentModel


class SqlAlchemyPaymentRepository:
    """SQLAlchemy-адаптер для порта домена репозитория платежей."""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory

    @property
    def _session(self) -> AsyncSession:
        return self._session_factory()

    async def try_insert(self, payment: Payment) -> Payment | None:
        """Вставляет платёж идемпотентно; возвращает None, если ключ уже существует.

        Использует ON CONFLICT DO NOTHING по уникальному idempotency_key,
        поэтому повторное создание является no-op, а не ошибкой.
        """
        result: CursorResult = await self._session.execute(
            insert(PaymentModel)
            .values(
                id=payment.id,
                idempotency_key=str(payment.idempotency_key),
                amount=payment.money.amount,
                currency=payment.money.currency.value,
                description=payment.description,
                metadata_=payment.metadata,
                status=payment.status.value,
                webhook_url=payment.webhook_url,
                correlation_id=payment.correlation_id,
                created_at=payment.created_at,
                processed_at=payment.processed_at,
                version=payment.version,
            )
            .on_conflict_do_nothing(index_elements=[PaymentModel.idempotency_key])
        )
        return payment if result.rowcount == 1 else None

    async def get(self, payment_id: UUID) -> Payment | None:
        """Возвращает платёж по первичному ключу или None, если его нет."""
        row: PaymentModel | None = await self._session.get(PaymentModel, payment_id)
        return to_domain(row) if row is not None else None

    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        """Возвращает платёж по его уникальному idempotency-ключу или None."""
        result = await self._session.execute(
            select(PaymentModel).where(PaymentModel.idempotency_key == idempotency_key)
        )
        row = result.scalar_one_or_none()
        return to_domain(row) if row is not None else None

    async def begin_processing(
        self,
        payment_id: UUID,
        expected_version: int,
        expected_status: PaymentStatus,
    ) -> bool:
        """Переводит pending -> processing под защитой проверок версии и статуса.

        ``expected_status`` приходит из конечного автомата агрегата (статус до
        перехода), поэтому SQL не хардкодит правила переходов — они живут в домене.
        Возвращает False, если платёж не в состоянии expected_status или его
        версия не совпадает; так конкурентные воркеры узнают, что проиграли гонку.
        """
        result: CursorResult = await self._session.execute(
            update(PaymentModel)
            .where(
                PaymentModel.id == payment_id,
                PaymentModel.status == expected_status.value,
                PaymentModel.version == expected_version,
            )
            .values(
                status=PaymentStatus.PROCESSING.value,
                version=PaymentModel.version + 1,
            )
        )
        return result.rowcount == 1

    async def mark_succeeded(
        self,
        payment_id: UUID,
        expected_version: int,
        expected_status: PaymentStatus,
        processed_at: datetime,
    ) -> bool:
        """Переводит processing -> succeeded под защитой проверок версии и статуса.

        ``expected_status`` приходит из конечного автомата агрегата (статус до
        перехода). Возвращает False, если платёж не был в этом статусе или версия
        устарела, защищая от повторной финализации.
        """
        result: CursorResult = await self._session.execute(
            update(PaymentModel)
            .where(
                PaymentModel.id == payment_id,
                PaymentModel.status == expected_status.value,
                PaymentModel.version == expected_version,
            )
            .values(
                status=PaymentStatus.SUCCEEDED.value,
                version=PaymentModel.version + 1,
                processed_at=processed_at,
            )
        )
        return result.rowcount == 1

    async def mark_failed(
        self,
        payment_id: UUID,
        expected_version: int,
        expected_status: PaymentStatus,
        processed_at: datetime,
    ) -> bool:
        """Переводит processing -> failed под защитой проверок версии и статуса.

        ``expected_status`` приходит из конечного автомата агрегата (статус до
        перехода). Возвращает False, если платёж не был в этом статусе или версия
        устарела, защищая от повторной финализации.
        """
        result: CursorResult = await self._session.execute(
            update(PaymentModel)
            .where(
                PaymentModel.id == payment_id,
                PaymentModel.status == expected_status.value,
                PaymentModel.version == expected_version,
            )
            .values(
                status=PaymentStatus.FAILED.value,
                version=PaymentModel.version + 1,
                processed_at=processed_at,
            )
        )
        return result.rowcount == 1


__all__ = ['SqlAlchemyPaymentRepository']
