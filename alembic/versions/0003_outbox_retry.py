"""Outbox: status и next_retry_at (лимит попыток и backoff)

Revision ID: 0003_outbox_retry
Revises: 0002_payments
Create Date: 2026-08-03
"""

import sqlalchemy as sa

from alembic import op

revision = '0003_outbox_retry'
down_revision = '0002_payments'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'outbox_messages',
        sa.Column(
            'status',
            sa.String(length=16),
            nullable=False,
            server_default='pending',
        ),
    )
    op.add_column(
        'outbox_messages',
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_index('ix_outbox_processed_created', table_name='outbox_messages')
    op.create_index(
        'ix_outbox_claim',
        'outbox_messages',
        ['status', 'next_retry_at', 'created_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_outbox_claim', table_name='outbox_messages')
    op.create_index(
        'ix_outbox_processed_created',
        'outbox_messages',
        ['processed_at', 'created_at'],
        unique=False,
    )
    op.drop_column('outbox_messages', 'next_retry_at')
    op.drop_column('outbox_messages', 'status')
