"""mutual fund holdings and their transactions

Revision ID: 0005_mutual_funds
Revises: 0004_corporate_actions
"""
from alembic import op
import sqlalchemy as sa


revision = '0005_mutual_funds'
down_revision = '0004_corporate_actions'
branch_labels = None
depends_on = None


def _ts():
    return [sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True)]


def upgrade() -> None:
    op.create_table('fund_holdings',
    sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('folio', sa.String(length=40), nullable=False),
    sa.Column('scheme_key', sa.String(length=20), nullable=False),
    sa.Column('scheme_code', sa.String(length=10), nullable=True),
    sa.Column('isin', sa.String(length=12), nullable=True),
    sa.Column('scheme_name', sa.String(length=200), nullable=False),
    sa.Column('units', sa.Float(), nullable=False),
    sa.Column('invested', sa.Float(), nullable=True),
    sa.Column('last_nav', sa.Float(), nullable=True),
    sa.Column('last_nav_date', sa.Date(), nullable=True),
    sa.Column('source', sa.String(length=10), nullable=False),
    *_ts(),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'folio', 'scheme_key', name='uq_fund_holding')
    )
    op.create_index(op.f('ix_fund_holdings_user_id'), 'fund_holdings', ['user_id'], unique=False)
    op.create_table('fund_transactions',
    sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('holding_id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('amount', sa.Float(), nullable=False),
    sa.Column('units', sa.Float(), nullable=False),
    *_ts(),
    sa.ForeignKeyConstraint(['holding_id'], ['fund_holdings.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_fund_transactions_holding_id'), 'fund_transactions', ['holding_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_fund_transactions_holding_id'), table_name='fund_transactions')
    op.drop_table('fund_transactions')
    op.drop_index(op.f('ix_fund_holdings_user_id'), table_name='fund_holdings')
    op.drop_table('fund_holdings')
