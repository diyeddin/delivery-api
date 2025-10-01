"""modify role column in User model

Revision ID: e236d41980f5
Revises: 18c4af47d098
Create Date: 2025-10-01 21:23:23.820271

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e236d41980f5'
down_revision: Union[str, Sequence[str], None] = '18c4af47d098'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create the enum type first (if it doesn't exist)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE userrole AS ENUM ('customer', 'driver', 'admin');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Convert the column with explicit casting
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE userrole USING role::userrole")


def downgrade() -> None:
    """Downgrade schema."""
    # Convert back to varchar
    op.alter_column('users', 'role',
               existing_type=sa.Enum('customer', 'driver', 'admin', name='userrole'),
               type_=sa.VARCHAR(),
               existing_nullable=True)
    
    # Drop the enum type
    op.execute("DROP TYPE userrole")
