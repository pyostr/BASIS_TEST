"""Тесты SQLAlchemy единицы работы: commit, rollback и идемпотентный rollback."""

import uuid

import pytest
from sqlalchemy import String, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from src.app.payments.infrastructure.uow import SqlAlchemyPaymentsUnitOfWork
from src.runtime.persistence.base import Base


class Widget(Base):
    """Простая тестовая сущность для проверки транзакций UoW."""

    __tablename__ = 'test_widgets'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50), nullable=False)


async def _ensure_table(engine):
    """Создаёт таблицы (включая test_widgets) на тестовом движке."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _count(engine) -> int:
    """Подсчитывает строки в таблице test_widgets."""
    async with engine.connect() as conn:
        result = await conn.execute(text('SELECT count(*) FROM test_widgets'))
        return result.scalar_one()


async def test_uow_commits_transaction(engine):
    """Commit в UoW сохраняет добавленные сущности."""
    await _ensure_table(engine)
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
        uow.session.add(Widget(name='committed'))
        await uow.commit()

    assert await _count(engine) == 1


async def test_uow_rolls_back_on_error(engine):
    """Исключение внутри контекста UoW откатывает все незакоммиченные изменения."""
    await _ensure_table(engine)
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

    with pytest.raises(RuntimeError):
        async with SqlAlchemyPaymentsUnitOfWork(sessionmaker) as uow:
            uow.session.add(Widget(name='rolled-back'))
            raise RuntimeError('boom')

    assert await _count(engine) == 0


async def test_uow_idempotent_rollback(engine):
    """Rollback до старта и повторные rollback безопасно ничего не делают."""
    await _ensure_table(engine)
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

    uow = SqlAlchemyPaymentsUnitOfWork(sessionmaker)
    await uow.rollback()  # не запущено -> бездействие
    async with uow:
        uow.session.add(Widget(name='discarded'))
        await uow.rollback()
        await uow.rollback()  # идемпотентно, без ошибки
        uow.session.add(Widget(name='final'))
        await uow.commit()

    assert await _count(engine) == 1
