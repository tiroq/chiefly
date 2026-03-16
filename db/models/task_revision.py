import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, JSON, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from core.domain.enums import ReviewAction, TaskKind
from db.base import Base


class TaskRevision(Base):
    __tablename__ = "task_revisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("task_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    proposal_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    user_decision: Mapped[str | None] = mapped_column(
        Enum(ReviewAction, name="review_action_enum", create_constraint=False), nullable=True
    )
    user_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    final_kind: Mapped[str | None] = mapped_column(
        Enum(TaskKind, name="task_kind_enum", create_constraint=False), nullable=True
    )
    final_project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    final_next_action: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
