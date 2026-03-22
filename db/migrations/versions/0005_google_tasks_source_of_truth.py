"""google tasks source of truth schema

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-22 18:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create task_records table
    op.create_table(
        "task_records",
        sa.Column("stable_id", sa.Uuid(), primary_key=True),
        sa.Column("current_tasklist_id", sa.String(255), nullable=True),
        sa.Column("current_task_id", sa.String(255), nullable=True),
        sa.Column("pointer_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_google_updated", sa.String(255), nullable=True),
        sa.Column("consecutive_misses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(50), nullable=False, server_default="unadopted"),
        sa.Column("processing_status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column(
            "processing_status_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_task_records_pointer",
        "task_records",
        ["current_tasklist_id", "current_task_id"],
        unique=True,
        postgresql_where=sa.text("current_tasklist_id IS NOT NULL AND current_task_id IS NOT NULL"),
    )
    op.create_index(
        "ix_task_records_processing",
        "task_records",
        ["processing_status", "processing_status_updated_at"],
    )
    op.create_index(
        "ix_task_records_state",
        "task_records",
        ["state", "last_seen_at"],
    )

    # 2. Create task_snapshots table
    op.create_table(
        "task_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "stable_id",
            sa.Uuid(),
            sa.ForeignKey("task_records.stable_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tasklist_id", sa.String(255), nullable=False),
        sa.Column("task_id", sa.String(255), nullable=False),
        sa.Column("google_updated", sa.String(255), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "is_latest",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.create_index(
        "ix_task_snapshots_tasklist_task",
        "task_snapshots",
        ["tasklist_id", "task_id", "fetched_at"],
    )
    op.create_index(
        "ix_task_snapshots_stable_id_fetched",
        "task_snapshots",
        ["stable_id", "fetched_at"],
    )
    op.create_index(
        "uq_task_snapshots_latest",
        "task_snapshots",
        ["stable_id"],
        unique=True,
        postgresql_where=sa.text("is_latest = true"),
    )
    op.create_index(
        "ix_task_snapshots_content_hash",
        "task_snapshots",
        ["content_hash"],
    )

    # 3. Add stable_id FK to task_revisions + new columns
    op.add_column(
        "task_revisions",
        sa.Column(
            "stable_id",
            sa.Uuid(),
            sa.ForeignKey("task_records.stable_id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "task_revisions",
        sa.Column("action", sa.String(50), nullable=True),
    )
    op.add_column(
        "task_revisions",
        sa.Column("actor_type", sa.String(50), nullable=True),
    )
    op.add_column(
        "task_revisions",
        sa.Column("actor_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "task_revisions",
        sa.Column("correlation_id", sa.Uuid(), nullable=True, unique=True),
    )
    op.add_column(
        "task_revisions",
        sa.Column("before_tasklist_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "task_revisions",
        sa.Column("before_task_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "task_revisions",
        sa.Column("before_state_json", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "task_revisions",
        sa.Column("after_tasklist_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "task_revisions",
        sa.Column("after_task_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "task_revisions",
        sa.Column("after_state_json", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "task_revisions",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "task_revisions",
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "task_revisions",
        sa.Column("success", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "task_revisions",
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_task_revisions_stable_id_created",
        "task_revisions",
        ["stable_id", "created_at"],
    )

    # 4. Add stable_id + proposed_changes to telegram_review_sessions
    op.add_column(
        "telegram_review_sessions",
        sa.Column(
            "stable_id",
            sa.Uuid(),
            sa.ForeignKey("task_records.stable_id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "telegram_review_sessions",
        sa.Column(
            "base_snapshot_id",
            sa.BigInteger(),
            sa.ForeignKey("task_snapshots.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "telegram_review_sessions",
        sa.Column("base_google_updated", sa.String(255), nullable=True),
    )
    op.add_column(
        "telegram_review_sessions",
        sa.Column(
            "proposed_changes",
            postgresql.JSONB(),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_trs_stable_id",
        "telegram_review_sessions",
        ["stable_id"],
    )

    # 5. Add stable_id to task_processing_queue
    op.add_column(
        "task_processing_queue",
        sa.Column(
            "stable_id",
            sa.Uuid(),
            sa.ForeignKey("task_records.stable_id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_tpq_stable_id",
        "task_processing_queue",
        ["stable_id"],
    )

    # 6. Add stable_id to system_events
    op.add_column(
        "system_events",
        sa.Column(
            "stable_id",
            sa.Uuid(),
            sa.ForeignKey("task_records.stable_id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_system_events_stable_id",
        "system_events",
        ["stable_id"],
    )


def downgrade() -> None:
    # 6. Remove stable_id from system_events
    op.drop_index("ix_system_events_stable_id", table_name="system_events")
    op.drop_column("system_events", "stable_id")

    # 5. Remove stable_id from task_processing_queue
    op.drop_index("ix_tpq_stable_id", table_name="task_processing_queue")
    op.drop_column("task_processing_queue", "stable_id")

    # 4. Remove new columns from telegram_review_sessions
    op.drop_index("ix_trs_stable_id", table_name="telegram_review_sessions")
    op.drop_column("telegram_review_sessions", "proposed_changes")
    op.drop_column("telegram_review_sessions", "base_google_updated")
    op.drop_column("telegram_review_sessions", "base_snapshot_id")
    op.drop_column("telegram_review_sessions", "stable_id")

    # 3. Remove new columns from task_revisions
    op.drop_index("ix_task_revisions_stable_id_created", table_name="task_revisions")
    op.drop_column("task_revisions", "error")
    op.drop_column("task_revisions", "success")
    op.drop_column("task_revisions", "finished_at")
    op.drop_column("task_revisions", "started_at")
    op.drop_column("task_revisions", "after_state_json")
    op.drop_column("task_revisions", "after_task_id")
    op.drop_column("task_revisions", "after_tasklist_id")
    op.drop_column("task_revisions", "before_state_json")
    op.drop_column("task_revisions", "before_task_id")
    op.drop_column("task_revisions", "before_tasklist_id")
    op.drop_column("task_revisions", "correlation_id")
    op.drop_column("task_revisions", "actor_id")
    op.drop_column("task_revisions", "actor_type")
    op.drop_column("task_revisions", "action")
    op.drop_column("task_revisions", "stable_id")

    # 2. Drop task_snapshots
    op.drop_index("ix_task_snapshots_content_hash", table_name="task_snapshots")
    op.drop_index("uq_task_snapshots_latest", table_name="task_snapshots")
    op.drop_index("ix_task_snapshots_stable_id_fetched", table_name="task_snapshots")
    op.drop_index("ix_task_snapshots_tasklist_task", table_name="task_snapshots")
    op.drop_table("task_snapshots")

    # 1. Drop task_records
    op.drop_index("ix_task_records_state", table_name="task_records")
    op.drop_index("ix_task_records_processing", table_name="task_records")
    op.drop_index("uq_task_records_pointer", table_name="task_records")
    op.drop_table("task_records")
