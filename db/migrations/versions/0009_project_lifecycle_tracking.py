"""Add project lifecycle tracking fields: first_seen_at, last_seen_at, deleted_at, last_synced_name.

Revision ID: 0009
Revises: 0008
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add lifecycle tracking columns to projects table."""
    # first_seen_at — backfill from created_at
    op.add_column(
        "projects",
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE projects SET first_seen_at = created_at")

    # last_seen_at — backfill from updated_at
    op.add_column(
        "projects",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE projects SET last_seen_at = updated_at")

    # deleted_at — null means not deleted
    op.add_column(
        "projects",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # last_synced_name — stores previous name on rename
    op.add_column(
        "projects",
        sa.Column("last_synced_name", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    """Remove lifecycle tracking columns from projects table."""
    op.drop_column("projects", "last_synced_name")
    op.drop_column("projects", "deleted_at")
    op.drop_column("projects", "last_seen_at")
    op.drop_column("projects", "first_seen_at")
