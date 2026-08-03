"""Outbox: finished_at, индексы для снятия lease и retention

Revision ID: 0005_outbox_finished
Revises: 0004_outbox_claim
Create Date: 2026-08-03
"""

import sqlalchemy as sa

from alembic import op

revision = '0005_outbox_finished'
down_revision = '0004_outbox_claim'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'outbox_messages',
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    )
    # Снятие просроченных lease: сканирование по claimed_at среди processing.
    op.create_index(
        'idx_outbox_claim_expiry',
        'outbox_messages',
        ['claimed_at'],
        unique=False,
        postgresql_where=sa.text("status = 'processing'"),
    )
    # Retention-очистка терминальных строк по finished_at.
    op.create_index(
        'idx_outbox_finished_at',
        'outbox_messages',
        ['finished_at'],
        unique=False,
        postgresql_where=sa.text("status IN ('processed', 'dead')"),
    )


def downgrade() -> None:
    op.drop_index('idx_outbox_finished_at', table_name='outbox_messages')
    op.drop_index('idx_outbox_claim_expiry', table_name='outbox_messages')
    op.drop_column('outbox_messages', 'finished_at')
