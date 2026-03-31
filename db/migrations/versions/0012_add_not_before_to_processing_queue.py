"""Add not_before column to task_processing_queue for delayed retry.

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "task_processing_queue",
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_tpq_not_before",
        "task_processing_queue",
        ["not_before"],
    )


def downgrade() -> None:
    op.drop_index("ix_tpq_not_before", table_name="task_processing_queue")
    op.drop_column("task_processing_queue", "not_before")
