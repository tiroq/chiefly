from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_processing_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("stable_id", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("step_name", sa.String(80), nullable=False),
        sa.Column("phase", sa.String(50), nullable=False),
        sa.Column("input_data", postgresql.JSONB(), nullable=True),
        sa.Column("output_data", postgresql.JSONB(), nullable=True),
        sa.Column("prompt_text", sa.Text(), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["stable_id"],
            ["task_records.stable_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_processing_logs_stable_id", "task_processing_logs", ["stable_id"])
    op.create_index(
        "ix_task_processing_logs_correlation_id", "task_processing_logs", ["correlation_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_task_processing_logs_correlation_id", table_name="task_processing_logs")
    op.drop_index("ix_task_processing_logs_stable_id", table_name="task_processing_logs")
    op.drop_table("task_processing_logs")
