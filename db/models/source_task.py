import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class SourceTask(Base):
    __tablename__ = "source_tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    google_task_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    google_tasklist_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title_raw: Mapped[str] = mapped_column(String(2000), nullable=False)
    notes_raw: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    google_status: Mapped[str] = mapped_column(String(50), nullable=False, default="needsAction")
    google_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_source_tasks_google_task_id", "google_task_id"),
        Index("ix_source_tasks_content_hash", "content_hash"),
        Index("ix_source_tasks_synced_at", "synced_at"),
    )
