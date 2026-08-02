"""Декларативная база SQLAlchemy, общая для всех ORM-моделей."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Декларативный базовый класс для всех ORM-моделей."""

    pass
