"""corporate actions confirmed by users (dividends, splits, bonuses)

Revision ID: 0004_corporate_actions
Revises: 0003_broker
"""
from alembic import op
import sqlalchemy as sa


revision = '0004_corporate_actions'
down_revision = '0003_broker'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('corporate_actions',
    sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('ticker', sa.String(length=20), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('ex_date', sa.Date(), nullable=False),
    sa.Column('amount', sa.Float(), nullable=True),
    sa.Column('ratio_new', sa.Float(), nullable=True),
    sa.Column('ratio_old', sa.Float(), nullable=True),
    sa.Column('source', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'ticker', 'kind', 'ex_date', name='uq_corp_action')
    )
    op.create_index(op.f('ix_corporate_actions_user_id'), 'corporate_actions', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_corporate_actions_user_id'), table_name='corporate_actions')
    op.drop_table('corporate_actions')
