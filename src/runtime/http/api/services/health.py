"""Сервисные функции, обеспечивающие работу health-эндпоинтов."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def check_database(engine: AsyncEngine) -> bool:
    """
    Проверяет доступность базы данных.

    Args:
        engine: асинхронный engine SQLAlchemy.

    Returns:
        True, если база данных доступна, иначе False.
    """

    try:
        async with engine.connect() as connection:
            await connection.execute(text('SELECT 1'))
        return True

    except Exception:
        return False
