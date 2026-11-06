"""alert delivery (telegram chat id, last message) and user feedback

Revision ID: 0002_alerts_feedback
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa


revision = '0002_alerts_feedback'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('telegram_chat_id', sa.String(length=32), nullable=True))
    op.add_column('alert_rules', sa.Column('last_message', sa.String(length=300), nullable=True))
    op.create_table('feedback',
    sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.UUID(as_uuid=False), nullable=True),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('page', sa.String(length=100), nullable=True),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_feedback_user_id'), 'feedback', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_feedback_user_id'), table_name='feedback')
    op.drop_table('feedback')
    op.drop_column('alert_rules', 'last_message')
    op.drop_column('users', 'telegram_chat_id')
