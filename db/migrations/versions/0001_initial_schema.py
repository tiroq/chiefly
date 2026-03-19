"""initial schema

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enums (PostgreSQL-specific; skipped automatically on other dialects)
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        for enum_name, values in [
            ("project_type_enum", ("client", "personal", "family", "ops", "writing", "internal")),
            ("task_kind_enum", ("task", "waiting", "commitment", "idea", "reference")),
            ("task_status_enum", ("new", "proposed", "confirmed", "routed", "completed", "discarded", "error")),
            ("confidence_band_enum", ("low", "medium", "high")),
            ("review_action_enum", ("confirm", "edit", "change_project", "change_type", "discard", "show_steps")),
        ]:
            pg_enum = postgresql.ENUM(*values, name=enum_name, create_type=True)
            pg_enum.create(bind, checkfirst=True)

    # projects
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("google_tasklist_id", sa.String(255), nullable=False),
        sa.Column("project_type", postgresql.ENUM("client", "personal", "family", "ops", "writing", "internal", name="project_type_enum", create_type=False), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )

    # task_items
    op.create_table(
        "task_items",
        sa.Column("id", sa.Uuid, nullable=False),
        sa.Column("source_google_task_id", sa.String(255), nullable=False),
        sa.Column("source_google_tasklist_id", sa.String(255), nullable=False),
        sa.Column("current_google_task_id", sa.String(255), nullable=True),
        sa.Column("current_google_tasklist_id", sa.String(255), nullable=True),
        sa.Column("raw_text", sa.String(2000), nullable=False),
        sa.Column("normalized_title", sa.String(500), nullable=True),
        sa.Column("kind", postgresql.ENUM("task", "waiting", "commitment", "idea", "reference", name="task_kind_enum", create_type=False), nullable=True),
        sa.Column("status", postgresql.ENUM("new", "proposed", "confirmed", "routed", "completed", "discarded", "error", name="task_status_enum", create_type=False), nullable=False, server_default="new"),
        sa.Column("project_id", sa.Uuid, nullable=True),
        sa.Column("next_action", sa.String(500), nullable=True),
        sa.Column("due_hint", sa.String(100), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("confidence_band", postgresql.ENUM("low", "medium", "high", name="confidence_band_enum", create_type=False), nullable=True),
        sa.Column("llm_model", sa.String(100), nullable=True),
        sa.Column("is_processed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_google_task_id"),
    )
    op.create_index("ix_task_items_status", "task_items", ["status"])
    op.create_index("ix_task_items_project_id", "task_items", ["project_id"])
    op.create_index("ix_task_items_created_at", "task_items", ["created_at"])

    # task_revisions
    op.create_table(
        "task_revisions",
        sa.Column("id", sa.Uuid, nullable=False),
        sa.Column("task_item_id", sa.Uuid, nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("proposal_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("user_decision", postgresql.ENUM("confirm", "edit", "change_project", "change_type", "discard", "show_steps", name="review_action_enum", create_type=False), nullable=True),
        sa.Column("user_notes", sa.Text(), nullable=True),
        sa.Column("final_title", sa.String(500), nullable=True),
        sa.Column("final_kind", postgresql.ENUM("task", "waiting", "commitment", "idea", "reference", name="task_kind_enum", create_type=False), nullable=True),
        sa.Column("final_project_id", sa.Uuid, nullable=True),
        sa.Column("final_next_action", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["task_item_id"], ["task_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_revisions_task_item_id", "task_revisions", ["task_item_id"])

    # telegram_review_sessions
    op.create_table(
        "telegram_review_sessions",
        sa.Column("id", sa.Uuid, nullable=False),
        sa.Column("task_item_id", sa.Uuid, nullable=False),
        sa.Column("telegram_chat_id", sa.String(100), nullable=False),
        sa.Column("telegram_message_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["task_item_id"], ["task_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_telegram_review_sessions_task_item_id", "telegram_review_sessions", ["task_item_id"])

    # daily_review_snapshots
    op.create_table(
        "daily_review_snapshots",
        sa.Column("id", sa.Uuid, nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_daily_review_snapshots_created_at", "daily_review_snapshots", ["created_at"])

    # processing_locks
    op.create_table(
        "processing_locks",
        sa.Column("id", sa.Uuid, nullable=False),
        sa.Column("lock_key", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lock_key"),
    )


def downgrade() -> None:
    op.drop_table("processing_locks")
    op.drop_table("daily_review_snapshots")
    op.drop_table("telegram_review_sessions")
    op.drop_table("task_revisions")
    op.drop_table("task_items")
    op.drop_table("projects")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for enum_name in [
            "review_action_enum", "confidence_band_enum",
            "task_status_enum", "task_kind_enum", "project_type_enum"
        ]:
            op.execute(f"DROP TYPE IF EXISTS {enum_name}")
