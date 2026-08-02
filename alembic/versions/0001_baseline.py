"""Исходная базовая миграция

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-31
"""

from alembic import op  # noqa: F401

revision = '0001_baseline'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Базовая миграция: бизнес-таблиц пока нет.
    # Платформенные таблицы будут добавлены миграциями фич.
    pass


def downgrade() -> None:
    pass
