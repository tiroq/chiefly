import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
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
    stable_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("task_records.stable_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    proposal_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    user_decision: Mapped[str | None] = mapped_column(
        Enum(
            ReviewAction,
            name="review_action_enum",
            create_constraint=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=True,
    )
    user_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    final_kind: Mapped[str | None] = mapped_column(
        Enum(
            TaskKind,
            name="task_kind_enum",
            create_constraint=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=True,
    )
    final_project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    final_next_action: Mapped[str | None] = mapped_column(String(500), nullable=True)
    action: Mapped[str | None] = mapped_column(String(50), nullable=True)
    actor_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, unique=True)
    before_tasklist_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    before_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    before_state_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_tasklist_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    after_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    after_state_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_task_revisions_stable_id_created", "stable_id", "created_at"),)
