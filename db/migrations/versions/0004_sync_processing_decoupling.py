"""sync processing decoupling

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-22 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("google_task_id", sa.String(255), nullable=False, unique=True),
        sa.Column("google_tasklist_id", sa.String(255), nullable=False),
        sa.Column("title_raw", sa.String(2000), nullable=False),
        sa.Column("notes_raw", sa.String(5000), nullable=True),
        sa.Column("google_status", sa.String(50), nullable=False, server_default="needsAction"),
        sa.Column("google_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_source_tasks_google_task_id", "source_tasks", ["google_task_id"])
    op.create_index("ix_source_tasks_content_hash", "source_tasks", ["content_hash"])
    op.create_index("ix_source_tasks_synced_at", "source_tasks", ["synced_at"])

    op.create_table(
        "task_processing_queue",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "source_task_id",
            sa.Uuid(),
            sa.ForeignKey("source_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_item_id",
            sa.Uuid(),
            sa.ForeignKey("task_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("processing_status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("processing_reason", sa.String(50), nullable=False),
        sa.Column("content_hash_at_processing", sa.String(64), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tpq_processing_status", "task_processing_queue", ["processing_status"])
    op.create_index("ix_tpq_source_task_id", "task_processing_queue", ["source_task_id"])
    op.create_index("ix_tpq_created_at", "task_processing_queue", ["created_at"])
    op.create_index(
        "ix_tpq_status_created", "task_processing_queue", ["processing_status", "created_at"]
    )

    op.add_column(
        "task_items",
        sa.Column(
            "source_task_id",
            sa.Uuid(),
            sa.ForeignKey("source_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_task_items_source_task_id", "task_items", ["source_task_id"])


def downgrade() -> None:
    op.drop_index("ix_task_items_source_task_id", table_name="task_items")
    op.drop_column("task_items", "source_task_id")
    op.drop_table("task_processing_queue")
    op.drop_table("source_tasks")
