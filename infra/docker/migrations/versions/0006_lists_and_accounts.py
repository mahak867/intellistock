"""several named watchlists; holdings and funds per family member (account)

Revision ID: 0006_lists_and_accounts
Revises: 0005_mutual_funds
"""
from alembic import op
import sqlalchemy as sa


revision = '0006_lists_and_accounts'
down_revision = '0005_mutual_funds'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('watchlist_items') as b:
        b.add_column(sa.Column('list_name', sa.String(length=40), nullable=False, server_default='Main'))
        b.drop_constraint('uq_watchlist_user_ticker', type_='unique')
        b.create_unique_constraint('uq_watchlist_user_list_ticker', ['user_id', 'list_name', 'ticker'])
    with op.batch_alter_table('portfolio_entries') as b:
        b.add_column(sa.Column('account', sa.String(length=40), nullable=False, server_default='Me'))
    with op.batch_alter_table('fund_holdings') as b:
        b.add_column(sa.Column('account', sa.String(length=40), nullable=False, server_default='Me'))
        b.drop_constraint('uq_fund_holding', type_='unique')
        b.create_unique_constraint('uq_fund_holding_account', ['user_id', 'account', 'folio', 'scheme_key'])


def downgrade() -> None:
    with op.batch_alter_table('fund_holdings') as b:
        b.drop_constraint('uq_fund_holding_account', type_='unique')
        b.create_unique_constraint('uq_fund_holding', ['user_id', 'folio', 'scheme_key'])
        b.drop_column('account')
    with op.batch_alter_table('portfolio_entries') as b:
        b.drop_column('account')
    with op.batch_alter_table('watchlist_items') as b:
        b.drop_constraint('uq_watchlist_user_list_ticker', type_='unique')
        b.create_unique_constraint('uq_watchlist_user_ticker', ['user_id', 'ticker'])
        b.drop_column('list_name')
