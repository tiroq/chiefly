from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_task_revisions_task_item_id", table_name="task_revisions")
    op.drop_column("task_revisions", "task_item_id")

    op.drop_index(
        "ix_telegram_review_sessions_task_item_id",
        table_name="telegram_review_sessions",
    )
    op.drop_column("telegram_review_sessions", "task_item_id")

    op.create_check_constraint(
        "ck_task_records_processing_status",
        "task_records",
        "processing_status IN ('pending', 'processing', 'awaiting_review', 'applied', 'discarded', 'failed')",
    )
    op.create_check_constraint(
        "ck_telegram_review_sessions_status",
        "telegram_review_sessions",
        "status IN ('queued', 'pending', 'awaiting_edit', 'send_failed', 'skipped', 'resolved')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_telegram_review_sessions_status",
        "telegram_review_sessions",
        type_="check",
    )
    op.drop_constraint(
        "ck_task_records_processing_status",
        "task_records",
        type_="check",
    )

    op.add_column(
        "telegram_review_sessions",
        sa.Column("task_item_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_telegram_review_sessions_task_item_id",
        "telegram_review_sessions",
        ["task_item_id"],
    )

    op.add_column(
        "task_revisions",
        sa.Column("task_item_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_task_revisions_task_item_id",
        "task_revisions",
        ["task_item_id"],
    )
