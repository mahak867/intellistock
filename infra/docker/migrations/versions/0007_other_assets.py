"""other assets: bank balances, deposits, PPF/EPF, NPS, bonds, gold

Revision ID: 0007_other_assets
Revises: 0006_lists_and_accounts
"""
from alembic import op
import sqlalchemy as sa


revision = '0007_other_assets'
down_revision = '0006_lists_and_accounts'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('other_assets',
    sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('account', sa.String(length=40), server_default='Me', nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('amount', sa.Float(), nullable=False),
    sa.Column('rate', sa.Float(), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('maturity_date', sa.Date(), nullable=True),
    sa.Column('as_of', sa.Date(), nullable=True),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_other_assets_user_id'), 'other_assets', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_other_assets_user_id'), table_name='other_assets')
    op.drop_table('other_assets')
