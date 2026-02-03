"""add payment_method and note to order

Revision ID: a17cb5c5d3ce
Revises: 7d18d8967445
Create Date: 2026-02-03 ...

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a17cb5c5d3ce'
down_revision = '7d18d8967445'
branch_labels = None
depends_on = None

# Define the Enum explicitly
payment_method_enum = sa.Enum('cash', 'transfer', name='paymentmethod')

def upgrade() -> None:
    # 1. Create the ENUM type first!
    payment_method_enum.create(op.get_bind())

    # 2. Now add the columns
    # We add server_default='cash' so existing rows don't crash the NOT NULL check
    op.add_column('orders', sa.Column('payment_method', payment_method_enum, nullable=False, server_default='cash'))
    op.add_column('orders', sa.Column('note', sa.String(), nullable=True))


def downgrade() -> None:
    # 1. Drop columns first
    op.drop_column('orders', 'note')
    op.drop_column('orders', 'payment_method')

    # 2. Drop the ENUM type last
    payment_method_enum.drop(op.get_bind())