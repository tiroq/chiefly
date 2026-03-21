"""add project description column

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-21 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add description column to projects table."""
    op.add_column("projects", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove description column from projects table."""
    op.drop_column("projects", "description")
