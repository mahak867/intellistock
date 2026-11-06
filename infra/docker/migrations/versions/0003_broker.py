"""broker connections and order audit log

Revision ID: 0003_broker
Revises: 0002_alerts_feedback
"""
from alembic import op
import sqlalchemy as sa


revision = '0003_broker'
down_revision = '0002_alerts_feedback'
branch_labels = None
depends_on = None


def _ts():
    return [sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True)]


def upgrade() -> None:
    op.create_table('broker_connections',
    sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('broker', sa.String(length=20), nullable=False),
    sa.Column('api_key', sa.String(length=64), nullable=False),
    sa.Column('api_secret_enc', sa.Text(), nullable=False),
    sa.Column('access_token_enc', sa.Text(), nullable=True),
    sa.Column('broker_user_id', sa.String(length=32), nullable=True),
    sa.Column('broker_user_name', sa.String(length=100), nullable=True),
    sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
    *_ts(),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_broker_connections_user_id'), 'broker_connections', ['user_id'], unique=True)
    op.create_table('order_log',
    sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('broker', sa.String(length=20), nullable=False),
    sa.Column('tradingsymbol', sa.String(length=30), nullable=False),
    sa.Column('exchange', sa.String(length=10), nullable=False),
    sa.Column('side', sa.String(length=4), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('price', sa.Float(), nullable=False),
    sa.Column('product', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('broker_order_id', sa.String(length=64), nullable=True),
    sa.Column('message', sa.String(length=300), nullable=True),
    sa.Column('confirm_sig', sa.String(length=64), nullable=True),
    *_ts(),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('confirm_sig')
    )
    op.create_index(op.f('ix_order_log_user_id'), 'order_log', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_order_log_user_id'), table_name='order_log')
    op.drop_table('order_log')
    op.drop_index(op.f('ix_broker_connections_user_id'), table_name='broker_connections')
    op.drop_table('broker_connections')
