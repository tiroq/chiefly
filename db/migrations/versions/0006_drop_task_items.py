from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE task_revisions DROP CONSTRAINT IF EXISTS task_revisions_task_item_id_fkey"
    )
    op.alter_column("task_revisions", "task_item_id", existing_type=sa.Uuid(), nullable=True)

    op.execute(
        "ALTER TABLE telegram_review_sessions DROP CONSTRAINT IF EXISTS telegram_review_sessions_task_item_id_fkey"
    )
    op.alter_column(
        "telegram_review_sessions", "task_item_id", existing_type=sa.Uuid(), nullable=True
    )

    op.execute(
        "ALTER TABLE task_processing_queue DROP CONSTRAINT IF EXISTS task_processing_queue_task_item_id_fkey"
    )
    op.drop_column("task_processing_queue", "task_item_id")

    op.execute(
        "ALTER TABLE system_events DROP CONSTRAINT IF EXISTS system_events_task_item_id_fkey"
    )
    op.drop_column("system_events", "task_item_id")

    op.drop_index("ix_task_items_source_task_id", table_name="task_items")
    op.drop_index("ix_task_items_created_at", table_name="task_items")
    op.drop_index("ix_task_items_project_id", table_name="task_items")
    op.drop_index("ix_task_items_status", table_name="task_items")
    op.drop_table("task_items")


def downgrade() -> None:
    raise NotImplementedError("Downgrade for 0006_drop_task_items is not implemented")
