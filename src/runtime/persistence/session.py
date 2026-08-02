"""Управление асинхронным engine и фабрикой сессий с синглтонами на весь процесс."""

import asyncio

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_lock = asyncio.Lock()


def _create_engine(settings) -> AsyncEngine:
    url = (
        f'{settings.POSTGRES_SCHEMA}://{settings.POSTGRES_USER}:'
        f'{settings.POSTGRES_PASSWORD}@'
        f'{settings.POSTGRES_HOST}:'
        f'{settings.POSTGRES_PORT}/'
        f'{settings.POSTGRES_DB}'
    )

    return create_async_engine(
        url,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=True,
        connect_args={
            'server_settings': {'statement_timeout': str(settings.DB_STATEMENT_TIMEOUT)}
        },
    )


async def get_engine(settings) -> AsyncEngine:
    """Возвращает асинхронный engine на весь процесс, создавая его лениво под блокировкой."""
    global _engine

    if _engine:
        return _engine

    async with _lock:
        if _engine is None:
            _engine = _create_engine(settings)

    return _engine


async def get_sessionmaker(settings) -> async_sessionmaker[AsyncSession]:
    """Возвращает кэшированную фабрику асинхронных сессий, привязанную к общему engine."""
    global _sessionmaker

    if _sessionmaker:
        return _sessionmaker

    engine = await get_engine(settings)

    _sessionmaker = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    return _sessionmaker


async def dispose_engine():
    """Освобождает общий engine и сбрасывает кэшированные синглтоны."""
    global _engine, _sessionmaker

    if _engine:
        await _engine.dispose()

    _engine = None
    _sessionmaker = None
