"""rename_cancelled_to_canceled

Revision ID: 02ebe4f7d052
Revises: a17cb5c5d3ce
Create Date: 2026-02-03 16:08:18.806128

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '02ebe4f7d052'
down_revision: Union[str, Sequence[str], None] = 'a17cb5c5d3ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Postgres command to rename an Enum value safely
    # This updates the Type definition and all existing data in one go
    op.execute("ALTER TYPE orderstatus RENAME VALUE 'cancelled' TO 'canceled'")


def downgrade() -> None:
    # Revert back if needed
    op.execute("ALTER TYPE orderstatus RENAME VALUE 'canceled' TO 'cancelled'")