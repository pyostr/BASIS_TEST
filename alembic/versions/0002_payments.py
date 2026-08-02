"""Платежи: payments, payment_attempts, outbox_messages, webhook_deliveries

Revision ID: 0002_payments
Revises: 0001_baseline
Create Date: 2026-07-31
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = '0002_payments'
down_revision = '0001_baseline'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'payments',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('idempotency_key', sa.String(length=255), nullable=False),
        sa.Column('amount', sa.Numeric(18, 2), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('webhook_url', sa.Text(), nullable=False),
        sa.Column('correlation_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint('amount > 0', name='ck_payments_amount_positive'),
        sa.CheckConstraint(
            "currency IN ('RUB', 'USD', 'EUR')", name='ck_payments_currency'
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'succeeded', 'failed')",
            name='ck_payments_status',
        ),
        sa.CheckConstraint(
            "webhook_url ~ '^https?://'", name='ck_payments_webhook_url'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_payments_status', 'payments', ['status'], unique=False)
    op.create_index('ix_payments_created_at', 'payments', ['created_at'], unique=False)
    op.create_index(
        'ix_payments_idempotency_key',
        'payments',
        ['idempotency_key'],
        unique=True,
    )

    op.create_table(
        'payment_attempts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('payment_id', sa.Uuid(), nullable=False),
        sa.Column('attempt_number', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column(
            'gateway_response', postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column('correlation_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('attempt_number > 0', name='ck_attempts_number'),
        sa.CheckConstraint(
            "status IN ('created', 'processing', 'succeeded', 'failed')",
            name='ck_attempts_status',
        ),
        sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_attempts_payment_id_number',
        'payment_attempts',
        ['payment_id', 'attempt_number'],
        unique=False,
    )

    op.create_table(
        'outbox_messages',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('aggregate_id', sa.Uuid(), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('correlation_id', sa.String(length=64), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_outbox_processed_created',
        'outbox_messages',
        ['processed_at', 'created_at'],
        unique=False,
    )

    op.create_table(
        'webhook_deliveries',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('payment_id', sa.Uuid(), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('response_code', sa.Integer(), nullable=True),
        sa.Column('response_body', sa.Text(), nullable=True),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('correlation_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'success', 'failed')",
            name='ck_webhook_deliveries_status',
        ),
        sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_webhook_deliveries_payment_event',
        'webhook_deliveries',
        ['payment_id', 'event_type'],
        unique=False,
    )
    op.create_index(
        'ix_webhook_deliveries_next_retry_at',
        'webhook_deliveries',
        ['next_retry_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        'ix_webhook_deliveries_next_retry_at', table_name='webhook_deliveries'
    )
    op.drop_index(
        'ix_webhook_deliveries_payment_event', table_name='webhook_deliveries'
    )
    op.drop_table('webhook_deliveries')
    op.drop_index('ix_outbox_processed_created', table_name='outbox_messages')
    op.drop_table('outbox_messages')
    op.drop_index('ix_attempts_payment_id_number', table_name='payment_attempts')
    op.drop_table('payment_attempts')
    op.drop_index('ix_payments_idempotency_key', table_name='payments')
    op.drop_index('ix_payments_status', table_name='payments')
    op.drop_index('ix_payments_created_at', table_name='payments')
    op.drop_table('payments')
