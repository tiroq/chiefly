import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from core.domain.enums import ConfidenceBand, TaskKind, TaskStatus
from db.base import Base


class TaskItem(Base):
    __tablename__ = "task_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_google_task_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    source_google_tasklist_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("source_tasks.id", ondelete="SET NULL"), nullable=True
    )
    current_google_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_google_tasklist_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_text: Mapped[str] = mapped_column(String(2000), nullable=False)
    normalized_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    kind: Mapped[str | None] = mapped_column(
        Enum(
            TaskKind,
            name="task_kind_enum",
            create_constraint=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        Enum(
            TaskStatus,
            name="task_status_enum",
            create_constraint=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=TaskStatus.NEW,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    next_action: Mapped[str | None] = mapped_column(String(500), nullable=True)
    due_hint: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_band: Mapped[str | None] = mapped_column(
        Enum(
            ConfidenceBand,
            name="confidence_band_enum",
            create_constraint=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=True,
    )
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_task_items_status", "status"),
        Index("ix_task_items_project_id", "project_id"),
        Index("ix_task_items_created_at", "created_at"),
        Index("ix_task_items_source_task_id", "source_task_id"),
    )
