"""account aggregator consents

Revision ID: 0008_aa_consents
Revises: 0007_other_assets
"""
from alembic import op
import sqlalchemy as sa


revision = '0008_aa_consents'
down_revision = '0007_other_assets'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('aa_consents',
    sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('user_id', sa.UUID(as_uuid=False), nullable=False),
    sa.Column('account', sa.String(length=40), server_default='Me', nullable=False),
    sa.Column('consent_id', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('session_id', sa.String(length=64), nullable=True),
    sa.Column('last_synced', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('consent_id')
    )
    op.create_index(op.f('ix_aa_consents_user_id'), 'aa_consents', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_aa_consents_user_id'), table_name='aa_consents')
    op.drop_table('aa_consents')
