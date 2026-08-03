"""Outbox: lease-захват (claimed_at, claimed_by)

Revision ID: 0004_outbox_claim
Revises: 0003_outbox_retry
Create Date: 2026-08-03
"""

import sqlalchemy as sa

from alembic import op

revision = '0004_outbox_claim'
down_revision = '0003_outbox_retry'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'outbox_messages',
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column('outbox_messages', sa.Column('claimed_by', sa.Uuid(), nullable=True))
    op.drop_index('ix_outbox_claim', table_name='outbox_messages')
    op.create_index(
        'idx_outbox_claim',
        'outbox_messages',
        ['status', 'next_retry_at', 'claimed_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('idx_outbox_claim', table_name='outbox_messages')
    op.create_index(
        'ix_outbox_claim',
        'outbox_messages',
        ['status', 'next_retry_at', 'created_at'],
        unique=False,
    )
    op.drop_column('outbox_messages', 'claimed_by')
    op.drop_column('outbox_messages', 'claimed_at')
