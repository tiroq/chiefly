"""Rename telegram_review_sessions.status 'pending' -> 'active'.

'pending' was ambiguous (collided with WorkflowStatus.PENDING which means
'not yet processed'). 'active' makes the meaning explicit: the item is
currently visible / actively under review in Telegram.

Also tightens the check constraint to remove the unused 'awaiting_edit' value.

Revision ID: 0013
Revises: 0012
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Migrate existing 'pending' rows to 'active' before constraint change.
    op.execute(
        "UPDATE telegram_review_sessions SET status = 'active' WHERE status = 'pending'"
    )

    # Replace the check constraint with the updated allowed values.
    op.drop_constraint(
        "ck_telegram_review_sessions_status",
        "telegram_review_sessions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_telegram_review_sessions_status",
        "telegram_review_sessions",
        "status IN ('queued', 'active', 'send_failed', 'skipped', 'resolved')",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE telegram_review_sessions SET status = 'pending' WHERE status = 'active'"
    )

    op.drop_constraint(
        "ck_telegram_review_sessions_status",
        "telegram_review_sessions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_telegram_review_sessions_status",
        "telegram_review_sessions",
        "status IN ('queued', 'pending', 'awaiting_edit', 'send_failed', 'skipped', 'resolved')",
    )
